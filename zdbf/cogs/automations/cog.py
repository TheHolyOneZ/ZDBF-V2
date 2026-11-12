# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ...core.database import utcnow_iso
from ...core.permissions import admin_or_owner
from ...ui import BaseView, FormField, FormModal, Paginator, Status, button, cards, confirm, row
from .actions import CUSTOM, build_context
from .builder import BuilderView, _fmt
from .engine import (
    CONDITION_HELP,
    VARIABLE_HELP,
    Automation,
    check_conditions,
    rule_types,
    validate_conditions,
)
from .persistent import PERSISTENT_ITEMS
from .templates import TEMPLATES, Runtime, level_for_xp, xp_for_level
from .transcripts import TranscriptStore

if TYPE_CHECKING:
    from ...core.bot import ZDBFBot

log = logging.getLogger("zdbf.automations")

MAX_PER_GUILD = 25
AUTO_DISABLE_AFTER = 10
HISTORY_KEEP = 200
COUNTER_CACHE_MAX = 50_000
TEMPLATE_CHOICES = [app_commands.Choice(name=t.name, value=t.id) for t in TEMPLATES.values()]


class AutomationView(BaseView):
    def __init__(self, cog: Automations, auto: Automation, author_id: int) -> None:
        super().__init__(author_id=author_id)
        self.cog = cog
        self.auto = auto

    def build(self) -> None:
        self.clear_items()
        box = self.cog.automation_card(self.auto)
        if self.auto.hook_id not in self.cog.index:
            self.add_item(cards.card("Deleted", f"`{self.auto.name}` was removed.", accent="muted"))
            return

        async def toggle(interaction: discord.Interaction[Any]) -> None:
            await self.cog.set_enabled(self.auto, not self.auto.enabled)
            await self.refresh(interaction)

        async def edit(interaction: discord.Interaction[Any]) -> None:
            builder = BuilderView(self.cog, TEMPLATES[self.auto.template], author_id=interaction.user.id,
                                  existing=self.auto, guild_id=self.auto.guild_id)
            await builder.send(interaction, ephemeral=True)

        async def conditions(interaction: discord.Interaction[Any]) -> None:
            async def done(modal_inter: discord.Interaction[Any], values: dict[str, str]) -> None:
                parsed, err = validate_conditions(values["json"])
                if err:
                    await modal_inter.response.send_message(view=cards.error("Invalid conditions", err), ephemeral=True)
                    return
                assert parsed is not None
                self.auto.conditions = parsed
                await self.cog.persist(self.auto)
                await self.refresh(modal_inter)

            current = json.dumps(self.auto.conditions.get("rules", []), indent=1)
            await interaction.response.send_modal(FormModal("Conditions", [FormField(
                "json", "Rules (JSON list - see /hooks conditions)", default=current, required=False, paragraph=True,
                max_length=3000)], done))

        async def cooldown(interaction: discord.Interaction[Any]) -> None:
            current = self.auto.config.get("__cooldown") or {}

            async def done(modal_inter: discord.Interaction[Any], values: dict[str, str]) -> None:
                try:
                    seconds = max(0, min(int(float(values["seconds"] or 0)), 7 * 24 * 3600))
                except ValueError:
                    await modal_inter.response.send_message(
                        view=cards.error("Invalid cooldown", "Seconds must be a number."), ephemeral=True)
                    return
                per = "server" if values["per"].strip().lower().startswith(("s", "g")) else "user"
                if seconds:
                    self.auto.config["__cooldown"] = {"seconds": seconds, "per": per}
                else:
                    self.auto.config.pop("__cooldown", None)
                await self.cog.persist(self.auto)
                await self.refresh(modal_inter)

            await interaction.response.send_modal(FormModal("Cooldown", [
                FormField("seconds", "Seconds between runs (0 = off)", default=str(current.get("seconds", 0)),
                          max_length=6),
                FormField("per", "Per user or per server", default=current.get("per", "user"), max_length=10,
                          description="user: each member has their own cooldown · server: one shared cooldown"),
            ], done))

        async def history(interaction: discord.Interaction[Any]) -> None:
            await (await self.cog.history_view(self.auto, interaction.user.id)).send(interaction, ephemeral=True)

        async def delete(interaction: discord.Interaction[Any]) -> None:
            await self.cog.delete_automation(self.auto)
            await self.refresh(interaction)
            self.stop()

        box.add_item(row(
            button("Disable" if self.auto.enabled else "Enable", toggle),
            button("Edit", edit),
            button("Conditions", conditions),
            button("Cooldown", cooldown),
            button("History", history),
        ))
        box.add_item(row(button("Delete", delete, style=discord.ButtonStyle.danger)))
        self.add_item(box)


class Automations(commands.Cog, name="Automations"):
    """No-code automations: welcome cards, role panels, tickets, levels, automod and more."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.guilds: dict[int, dict[str, Automation]] = {}
        self.index: dict[str, Automation] = {}
        self.runtime = Runtime(self)
        self.transcripts = TranscriptStore()
        self._session: aiohttp.ClientSession | None = None
        self._dirty: set[str] = set()
        self._ticker: asyncio.Task[None] | None = None
        self._runs: list[tuple[Any, ...]] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self._counts: dict[tuple[int, int], int] = {}
        self._counts_dirty: set[tuple[int, int]] = set()

    async def cog_load(self) -> None:
        for r in await self.bot.db.fetchall("SELECT * FROM automations"):
            self._add(Automation.from_row(r))
        self.bot.add_dynamic_items(*PERSISTENT_ITEMS)
        self._ticker = asyncio.create_task(self._tick_loop(), name="zdbf-automations")

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(*PERSISTENT_ITEMS)
        if self._ticker:
            self._ticker.cancel()
        for task in list(self._tasks):
            task.cancel()
        await self._flush()
        if self._session:
            await self._session.close()

    async def http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": "ZDBF-Automations/2"})
        return self._session

    def _add(self, auto: Automation) -> None:
        self.guilds.setdefault(auto.guild_id, {})[auto.hook_id] = auto
        self.index[auto.hook_id] = auto

    def find(self, hook_id: str) -> Automation | None:
        return self.index.get(hook_id)

    def for_guild(self, guild_id: int) -> list[Automation]:
        return sorted(self.guilds.get(guild_id, {}).values(), key=lambda a: a.name.lower())

    async def dispatch(self, guild_id: int | None, event: str, payload: dict[str, Any] | None = None, *,
                       member: discord.Member | None = None, channel_id: int | None = None,
                       content: str | None = None) -> None:
        if guild_id is None or not (autos := self.guilds.get(guild_id)):
            return
        payload = payload or {}
        for auto in list(autos.values()):
            template = TEMPLATES.get(auto.template)
            handler = template.handlers.get(event) if template else None
            if handler is None or template is None or not auto.enabled:
                continue
            if template.accepts is not None and not template.accepts(auto, event, payload):
                continue
            if (event != "tick" or template.background) and auto.conditions.get("rules"):
                context: dict[str, Any] = {}
                types = rule_types(auto.conditions)
                if "message_count" in types and member is not None:
                    context["message_count"] = await self.message_count(guild_id, member.id)
                if "variable" in types:
                    context.update(build_context(self.bot, guild_id, event, payload)["values"])
                if not check_conditions(auto.conditions, member=member, channel_id=channel_id, content=content,
                                        context=context):
                    continue
            if not self._cooldown_ok(auto, member):
                continue
            meta = (event, member.id if member else None, channel_id)
            if template.background:
                task = asyncio.create_task(self._run(auto, handler, payload, template.timeout, meta),
                                           name=f"zdbf-automation-{auto.hook_id}")
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            else:
                await self._run(auto, handler, payload, template.timeout, meta)

    def _cooldown_ok(self, auto: Automation, member: discord.Member | None) -> bool:
        cd = auto.config.get("__cooldown") or {}
        seconds = float(cd.get("seconds") or 0)
        if seconds <= 0:
            return True
        scope = member.id if cd.get("per", "user") == "user" and member is not None else 0
        return self.runtime.throttle(f"cd:{auto.hook_id}:{scope}", seconds)

    async def _run(self, auto: Automation, handler: Any, payload: dict[str, Any], timeout: float = 15,
                   meta: tuple[str, int | None, int | None] = ("manual", None, None)) -> None:
        started = time.perf_counter()
        error: str | None = None
        try:
            result = await asyncio.wait_for(handler(self.runtime, auto, **payload), timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = None
            error = f"{type(exc).__name__}: {cards.truncate(exc, 300)}"
            if isinstance(exc, TimeoutError):
                error = f"timed out after {timeout:.0f} s"
            auto.error_count += 1
            auto.consecutive_errors += 1
            auto.last_error = error
            log.warning("automation %s (%s) failed: %s", auto.name, auto.hook_id, error)
            if auto.consecutive_errors >= AUTO_DISABLE_AFTER:
                auto.enabled = False
                await self.bot.alerts.send("automations", f"`{auto.name}` in server `{auto.guild_id}` was disabled "
                                                          f"after {AUTO_DISABLE_AFTER} errors: {error}", "error")
        if result is False:
            return
        if error is None:
            auto.run_count += 1
            auto.consecutive_errors = 0
            auto.last_run = utcnow_iso()
        event, user_id, channel_id = meta
        self._runs.append((auto.hook_id, auto.guild_id, utcnow_iso(), event, int(error is None), user_id, channel_id,
                           int((time.perf_counter() - started) * 1000), error))
        self._dirty.add(auto.hook_id)

    def _counts_messages(self, guild_id: int) -> bool:
        return any("message_count" in rule_types(a.conditions) for a in self.guilds.get(guild_id, {}).values())

    async def message_count(self, guild_id: int, user_id: int) -> int:
        key = (guild_id, user_id)
        if key not in self._counts:
            raw = await self.bot.db.fetchval(
                "SELECT value FROM automation_state WHERE hook_id = ? AND scope_id = ? AND key = 'messages'",
                (f"guild:{guild_id}", user_id))
            self._counts[key] = int(json.loads(raw)) if raw is not None else 0
        return self._counts[key]

    async def _count_message(self, guild_id: int, user_id: int) -> None:
        self._counts[(guild_id, user_id)] = await self.message_count(guild_id, user_id) + 1
        self._counts_dirty.add((guild_id, user_id))

    async def _tick_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            await asyncio.sleep(60)
            for guild_id in list(self.guilds):
                with contextlib.suppress(Exception):
                    await self.dispatch(guild_id, "tick", {})
            await self._flush()

    async def _flush(self) -> None:
        dirty, self._dirty = self._dirty, set()
        runs, self._runs = self._runs, []
        counts, self._counts_dirty = self._counts_dirty, set()
        for hook_id in dirty:
            if auto := self.index.get(hook_id):
                await self.persist(auto)
        runs = [r for r in runs if r[0] in self.index]
        if runs or counts:
            async with self.bot.db.transaction() as conn:
                if runs:
                    await conn.executemany(
                        "INSERT INTO automation_runs (hook_id, guild_id, at, event, ok, user_id, channel_id, "
                        "duration_ms, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", runs)
                    for hook_id in {r[0] for r in runs}:
                        await conn.execute(
                            "DELETE FROM automation_runs WHERE hook_id = ? AND id NOT IN (SELECT id FROM "
                            "automation_runs WHERE hook_id = ? ORDER BY id DESC LIMIT ?)", (hook_id, hook_id, HISTORY_KEEP))
                if counts:
                    await conn.executemany(
                        "INSERT INTO automation_state (hook_id, scope_id, key, value) VALUES (?, ?, 'messages', ?) "
                        "ON CONFLICT(hook_id, scope_id, key) DO UPDATE SET value = excluded.value",
                        [(f"guild:{g}", u, json.dumps(self._counts.get((g, u), 0))) for g, u in counts])
        if len(self._counts) > COUNTER_CACHE_MAX:
            self._counts.clear()
        self.runtime.prune()

    async def persist(self, auto: Automation) -> None:
        auto.updated_at = utcnow_iso()
        await self.bot.db.execute(
            "INSERT INTO automations (hook_id, guild_id, name, template, config, conditions, enabled, created_by, "
            "created_at, updated_at, run_count, error_count, last_run, last_error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hook_id) DO UPDATE SET "
            "name = excluded.name, config = excluded.config, conditions = excluded.conditions, "
            "enabled = excluded.enabled, updated_at = excluded.updated_at, run_count = excluded.run_count, "
            "error_count = excluded.error_count, last_run = excluded.last_run, last_error = excluded.last_error",
            (auto.hook_id, auto.guild_id, auto.name, auto.template, json.dumps(auto.config),
             json.dumps(auto.conditions), int(auto.enabled), auto.created_by, auto.created_at or utcnow_iso(),
             auto.updated_at, auto.run_count, auto.error_count, auto.last_run, auto.last_error),
        )

    async def save_automation(self, *, guild: discord.Guild | None, template: Any, name: str, config: dict[str, Any],
                              author_id: int, existing: Automation | None = None) -> Automation:
        if guild is None:
            raise RuntimeError("automations only work in servers")
        if missing := template.missing(config):
            raise ValueError("missing: " + ", ".join(p.label for p in missing))
        if problems := template.problems(config):
            raise ValueError("; ".join(problems))
        if existing is None and len(self.guilds.get(guild.id, {})) >= MAX_PER_GUILD:
            raise ValueError(f"this server already has {MAX_PER_GUILD} automations")
        auto = existing or Automation(hook_id=secrets.token_hex(4), guild_id=guild.id, name=name,
                                      template=template.id, config={}, created_by=author_id,
                                      created_at=utcnow_iso())
        auto.name = name
        auto.config = dict(config)
        if template.on_create is not None:
            await template.on_create(self.runtime, auto)
        self._add(auto)
        await self.persist(auto)
        return auto

    async def delete_automation(self, auto: Automation) -> None:
        template = TEMPLATES.get(auto.template)
        if template and template.on_delete:
            with contextlib.suppress(Exception):
                await template.on_delete(self.runtime, auto)
        self.index.pop(auto.hook_id, None)
        self.guilds.get(auto.guild_id, {}).pop(auto.hook_id, None)
        async with self.bot.db.transaction() as conn:
            await conn.execute("DELETE FROM automations WHERE hook_id = ?", (auto.hook_id,))
            await conn.execute("DELETE FROM automation_state WHERE hook_id = ?", (auto.hook_id,))
            await conn.execute("DELETE FROM automation_runs WHERE hook_id = ?", (auto.hook_id,))
        self._runs = [r for r in self._runs if r[0] != auto.hook_id]

    async def set_enabled(self, auto: Automation, enabled: bool) -> None:
        auto.enabled = enabled
        auto.consecutive_errors = 0
        await self.persist(auto)

    def automation_card(self, auto: Automation, *, title_prefix: str = "") -> discord.ui.Container[Any]:
        template = TEMPLATES.get(auto.template)
        params = "\n".join(f"**{p.label}** · {_fmt(p, auto.config.get(p.key))}"
                           for p in (template.visible(auto.config) if template else ()))
        if template is CUSTOM:
            from .actions import summarize

            steps = [f"`{i}.` {summarize(a)}" for i, a in enumerate(auto.config.get("actions") or [], 1)]
            params += "\n" + ("\n".join(steps) if steps else "*no actions*")
        rules = auto.conditions.get("rules", [])
        total = auto.run_count + auto.error_count
        cd = auto.config.get("__cooldown") or {}
        return cards.card(
            title_prefix + auto.name,
            f"{template.name if template else auto.template} · "
            f"{'enabled' if auto.enabled else 'disabled'} · id `{auto.hook_id}`",
            cards.sep(),
            params or "*no settings*",
            cards.sep(),
            cards.kv({
                "Conditions": (f"{len(rules)} rule(s), {auto.conditions.get('logic', 'and').upper()}" if rules else "none"),
                "Cooldown": f"{cd['seconds']} s per {cd.get('per', 'user')}" if cd.get("seconds") else "none",
                "Runs": f"{auto.run_count:,}", "Errors": f"{auto.error_count:,}",
                "Success rate": f"{auto.run_count / total * 100:.1f}%" if total else "-",
                "Last run": auto.last_run or "never", "Created by": f"<@{auto.created_by}>",
            }),
            f"-# Last error: {auto.last_error}" if auto.last_error else None,
            emoji=None, accent="primary" if auto.enabled else "muted",
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._member_event("member_join", member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self._member_event("member_remove", member)

    async def _member_event(self, event: str, member: discord.Member) -> None:
        await self.dispatch(member.guild.id, event, {"member": member}, member=member)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or message.guild.id not in self.guilds:
            return
        member = message.author if isinstance(message.author, discord.Member) else None
        if member is not None and self._counts_messages(message.guild.id):
            await self._count_message(message.guild.id, member.id)
        await self.dispatch(message.guild.id, "message", {"message": message}, member=member,
                            channel_id=message.channel.id, content=message.content)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if self.bot.user and payload.user_id != self.bot.user.id and payload.guild_id in self.guilds:
            await self.dispatch(payload.guild_id, "reaction_add", {"payload": payload}, member=payload.member,
                                channel_id=payload.channel_id)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if self.bot.user and payload.user_id != self.bot.user.id and payload.guild_id in self.guilds:
            await self.dispatch(payload.guild_id, "reaction_remove", {"payload": payload}, channel_id=payload.channel_id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState) -> None:
        if member.guild.id not in self.guilds or member.bot:
            return
        await self.dispatch(member.guild.id, "voice", {"member": member, "before": before, "after": after},
                            member=member, channel_id=after.channel.id if after.channel else None)

    async def _auto_ac(self, interaction: discord.Interaction[Any], current: str) -> list[app_commands.Choice[str]]:
        autos = self.for_guild(interaction.guild_id or 0)
        return [app_commands.Choice(name=f"{a.name} ({a.hook_id})"[:100], value=a.hook_id) for a in autos
                if current.lower() in a.name.lower() or current in a.hook_id][:25]

    def _resolve(self, guild_id: int, ref: str) -> Automation | None:
        autos = self.for_guild(guild_id)
        return next((a for a in autos if a.hook_id == ref), None) or next(
            (a for a in autos if a.name.lower() == ref.lower()), None)

    @commands.hybrid_group(name="hooks", description="Server automations", invoke_without_command=True)
    @commands.guild_only()
    async def hooks(self, ctx: commands.Context[ZDBFBot]) -> None:
        await self.hooks_list.callback(self, ctx)  # type: ignore[arg-type]

    @hooks.command(name="create", description="Create an automation with the visual builder")
    @app_commands.describe(template="What kind of automation")
    @app_commands.choices(template=TEMPLATE_CHOICES)
    @commands.guild_only()
    @admin_or_owner()
    async def hooks_create(self, ctx: commands.Context[ZDBFBot], template: str) -> None:
        tpl = TEMPLATES.get(template.lower())
        if tpl is None:
            await ctx.send(view=cards.error("Unknown template", "See `/hooks templates` for the list."))
            return
        await BuilderView(self, tpl, author_id=ctx.author.id, guild_id=ctx.guild.id if ctx.guild else None).send(ctx)

    @hooks.command(name="templates", description="Available automation templates")
    async def hooks_templates(self, ctx: commands.Context[ZDBFBot]) -> None:
        lines = [f"**{t.name}**  `{t.id}`\n-# {t.description}" for t in TEMPLATES.values()]
        await Paginator.from_lines(lines, per_page=6, title="Automation templates",
                                   foot="Create one with /hooks create").send(ctx)

    @hooks.command(name="list", description="Automations in this server")
    @commands.guild_only()
    async def hooks_list(self, ctx: commands.Context[ZDBFBot]) -> None:
        assert ctx.guild is not None
        autos = self.for_guild(ctx.guild.id)
        lines = []
        for a in autos:
            t = TEMPLATES.get(a.template)
            state = Status.OK if a.enabled else Status.OFF
            err = f" · {Status.WARN} {a.error_count} errors" if a.error_count else ""
            lines.append(f"{state} **{a.name}**  {t.name if t else a.template} · `{a.hook_id}` · {a.run_count:,} runs{err}")
        await Paginator.from_lines(lines or ["*No automations yet - start with `/hooks create`.*"], per_page=10,
                                   title="Automations",
                                   subtitle=f"{len(autos)}/{MAX_PER_GUILD} used").send(ctx)

    @hooks.command(name="info", description="Show and manage an automation")
    @app_commands.autocomplete(automation=_auto_ac)
    @commands.guild_only()
    @admin_or_owner()
    async def hooks_info(self, ctx: commands.Context[ZDBFBot], *, automation: str) -> None:
        assert ctx.guild is not None
        auto = self._resolve(ctx.guild.id, automation)
        if auto is None:
            await ctx.send(view=cards.error("Not found", f"No automation `{automation}` here."))
            return
        await AutomationView(self, auto, ctx.author.id).send(ctx)

    async def history_view(self, auto: Automation, author_id: int) -> Paginator:
        await self._flush()
        rows = await self.bot.db.fetchall(
            "SELECT * FROM automation_runs WHERE hook_id = ? ORDER BY id DESC LIMIT ?", (auto.hook_id, HISTORY_KEEP))
        lines = []
        for r in rows:
            when = cards.timestamp(r["at"], "R") if r["at"] else "-"
            who = f" · <@{r['user_id']}>" if r["user_id"] else ""
            where = f" · <#{r['channel_id']}>" if r["channel_id"] else ""
            line = f"{Status.OK if r['ok'] else Status.ERROR} {when} · {r['event']}{who}{where} · {r['duration_ms']} ms"
            if r["error"]:
                line += f"\n-# {cards.truncate(r['error'], 180)}"
            lines.append(line)
        ok = sum(1 for r in rows if r["ok"])
        subtitle = (f"Last {len(rows)} runs · {ok / len(rows) * 100:.1f}% successful" if rows else "No runs yet")
        return Paginator.from_lines(lines or ["*This automation has not run yet.*"], per_page=10,
                                    title=f"History · {auto.name}", subtitle=subtitle, author_id=author_id,
                                    foot=f"The newest {HISTORY_KEEP} runs are kept")

    @hooks.command(name="history", description="Recent runs of an automation")
    @app_commands.autocomplete(automation=_auto_ac)
    @commands.guild_only()
    @admin_or_owner()
    async def hooks_history(self, ctx: commands.Context[ZDBFBot], *, automation: str) -> None:
        assert ctx.guild is not None
        auto = self._resolve(ctx.guild.id, automation)
        if auto is None:
            await ctx.send(view=cards.error("Not found", f"No automation `{automation}` here."))
            return
        await (await self.history_view(auto, ctx.author.id)).send(ctx)

    @hooks.command(name="toggle", description="Enable or disable an automation")
    @app_commands.autocomplete(automation=_auto_ac)
    @commands.guild_only()
    @admin_or_owner()
    async def hooks_toggle(self, ctx: commands.Context[ZDBFBot], *, automation: str) -> None:
        assert ctx.guild is not None
        auto = self._resolve(ctx.guild.id, automation)
        if auto is None:
            await ctx.send(view=cards.error("Not found", f"No automation `{automation}` here."))
            return
        await self.set_enabled(auto, not auto.enabled)
        await ctx.send(view=cards.success(f"{'Enabled' if auto.enabled else 'Disabled'}", f"`{auto.name}`"))

    @hooks.command(name="delete", description="Delete an automation")
    @app_commands.autocomplete(automation=_auto_ac)
    @commands.guild_only()
    @admin_or_owner()
    async def hooks_delete(self, ctx: commands.Context[ZDBFBot], *, automation: str) -> None:
        assert ctx.guild is not None
        auto = self._resolve(ctx.guild.id, automation)
        if auto is None:
            await ctx.send(view=cards.error("Not found", f"No automation `{automation}` here."))
            return
        view = await confirm(ctx, "Delete automation?", f"`{auto.name}` and its stored data (XP, tickets…) "
                                                        "will be removed.", confirm_label="Delete")
        if view.value:
            await self.delete_automation(auto)

    @hooks.command(name="conditions", description="How to write automation conditions")
    async def hooks_conditions(self, ctx: commands.Context[ZDBFBot]) -> None:
        await Paginator([CONDITION_HELP + "\nEdit them with the **Conditions** button in `/hooks info`.",
                         "**Variables** (messages, titles, role names, webhook payloads)\n" + VARIABLE_HELP],
                        title="Conditions and variables").send(ctx)

    @hooks.command(name="rank", description="Your XP and level")
    @commands.guild_only()
    async def hooks_rank(self, ctx: commands.Context[ZDBFBot], member: discord.Member | None = None) -> None:
        assert ctx.guild is not None
        member = member or ctx.author  # type: ignore[assignment]
        assert member is not None
        auto = next((a for a in self.for_guild(ctx.guild.id) if a.template == "leveling"), None)
        if auto is None:
            await ctx.send(view=cards.warning("Leveling is off", "Create an `XP & levels` automation first."))
            return
        xp = int(await self.runtime.state_get(auto, member.id, "xp", 0))
        level = level_for_xp(xp)
        position = await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM automation_state WHERE hook_id = ? AND key = 'xp' AND CAST(value AS INTEGER) > ?",
            (auto.hook_id, xp), default=0) + 1
        start, goal = xp_for_level(level), xp_for_level(level + 1)
        await ctx.send(view=cards.static(cards.card(
            member.display_name,
            cards.kv({"Level": level, "XP": f"{xp:,}", "Rank": f"#{position}"}),
            f"{cards.bar(xp - start, goal - start, 16)} to level {level + 1} ({goal - xp:,} XP left)", accent="gold", thumbnail=member.display_avatar.url)))

    @hooks.command(name="leaderboard", description="Top members by XP")
    @commands.guild_only()
    async def hooks_leaderboard(self, ctx: commands.Context[ZDBFBot]) -> None:
        assert ctx.guild is not None
        auto = next((a for a in self.for_guild(ctx.guild.id) if a.template == "leveling"), None)
        if auto is None:
            await ctx.send(view=cards.warning("Leveling is off", "Create an `XP & levels` automation first."))
            return
        rows = await self.bot.db.fetchall(
            "SELECT scope_id, CAST(value AS INTEGER) AS xp FROM automation_state WHERE hook_id = ? AND key = 'xp' "
            "ORDER BY xp DESC LIMIT 100", (auto.hook_id,))
        lines = [f"`{i:>3}.` <@{r['scope_id']}>  level **{level_for_xp(r['xp'])}** · {r['xp']:,} XP"
                 for i, r in enumerate(rows, 1)]
        await Paginator.from_lines(lines or ["*Nobody has XP yet.*"], per_page=10, title="Leaderboard", accent="gold", subtitle=ctx.guild.name).send(ctx)
