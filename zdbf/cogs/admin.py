# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import discord
from discord import app_commands
from discord.ext import commands

from ..core.config import Config, ConfigError, Settings
from ..core.extensions import BUILTIN_MODULES
from ..core.permissions import is_owner_only, owner_only
from ..core.schema import ValidationResult, validate_against
from ..core.storage import global_file_handler
from ..ui import BaseView, Glyph, Paginator, SelectPager, Status, button, cards, confirm, row, status_dot
from ..utils import human_bytes
from .core import send_group_help

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot

ALERT_SYSTEMS = (
    "default", "errors", "diagnostics", "eventhooks", "plugins", "extensions",
    "shards", "cluster", "backup", "scheduler", "automations", "marketplace", "database", "dashboard",
)
SECRET_HINTS = ("token", "secret", "password", "api_key", "apikey")


def _redact(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: ("•••" if any(h in k.lower() for h in SECRET_HINTS) else _redact(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [_redact(v) for v in data]
    return data


def _result_view(results: list[Any], title: str) -> Paginator:
    lines = []
    for r in results:
        if r.ok:
            lines.append(f"{Status.OK} **{r.name}**  {r.action}ed in `{r.elapsed_ms:.0f} ms`"
                         + (f"\n-# {r.note}" if r.note else ""))
        else:
            lines.append(f"{Status.ERROR} **{r.name}**  {cards.truncate(r.error, 300)}"
                         + (f"\n-# {r.note}" if r.note else ""))
    ok = all(r.ok for r in results)
    done = sum(r.ok for r in results)
    return Paginator.from_lines(lines or ["Nothing to do."], per_page=12, title=title,
                                subtitle=f"{done} of {len(results)} succeeded", accent="success" if ok else "error",
                                foot="Slash commands re-sync automatically when they change")


class DatabaseView(BaseView):
    def __init__(self, bot: ZDBFBot, stats: dict[str, Any], author_id: int) -> None:
        super().__init__(author_id=author_id)
        self.bot = bot
        self.stats = stats
        self.note: str | None = None
        self.mode = "overview"
        self.picker = SelectPager([], self._pick_backup, placeholder="Choose a backup to restore")

    async def _reload(self) -> None:
        self.stats = await self.bot.db.stats()

    async def _pick_backup(self, interaction: discord.Interaction[Any], values: list[str]) -> None:
        try:
            path = self.bot.db.request_restore(values[0])
        except ValueError as exc:
            self.note = f"{Status.ERROR} {exc}"
        else:
            self.note = (f"{Status.WARN} `{path.name}` will replace the database on the next start. "
                         "The current file is kept as a `.replaced` copy.")
        self.mode = "overview"
        await self._reload()
        await self.refresh(interaction)

    def build(self) -> None:
        self.clear_items()
        s = self.stats
        db = self.bot.db
        if self.mode == "restore":
            backups = db.list_backups()
            lines = [f"`{p.name}`  {human_bytes(p.stat().st_size)} · "
                     f"{cards.timestamp(p.stat().st_mtime, 'f')}" for p in backups]
            box = cards.card("Restore database", "Pick a backup. It is applied on the next start, never while the "
                             "bot is running, and the current file is kept.", cards.sep(),
                             "\n".join(lines[:10]) + (f"\n-# and {len(lines) - 10} older" if len(lines) > 10 else "")
                             if lines else "*No backups yet.*", accent="warning")
            self.picker.set_options([discord.SelectOption(label=p.name[:100], value=str(p),
                                                          description=human_bytes(p.stat().st_size)) for p in backups])
            for r in self.picker.rows(self):
                box.add_item(r)

            async def back(interaction: discord.Interaction[Any]) -> None:
                self.mode = "overview"
                await self.refresh(interaction)

            box.add_item(row(button(f"{Glyph.PREV} Back", back)))
            self.add_item(box)
            return

        tables = "\n".join(f"`{name}`  {count:,}" for name, count in s["tables"].items())
        box = cards.card(
            "Database",
            cards.kv({"File": f"`{s['path']}`", "Size": human_bytes(s["size_bytes"]),
                      "Schema version": s["schema_version"], "Queries this session": f"{s['queries']:,}",
                      "Lock retries": s["busy_retries"], "Backups": s["backups"],
                      "Restore pending": "yes, on next start" if s["restore_pending"] else "no",
                      "Legacy V1 server databases open": s["legacy_guild_connections"]}),
            cards.sep(),
            "**Tables**\n" + tables,
            self.note,
            subtitle="SQLite · WAL · separate reader connection",
            accent="primary",
        )

        async def do_backup(interaction: discord.Interaction[Any]) -> None:
            await interaction.response.defer()
            path = await db.backup()
            self.note = f"{Status.OK} Backup written to `{path.name}`."
            await self._reload()
            await self.refresh(interaction)

        async def do_check(interaction: discord.Interaction[Any]) -> None:
            await interaction.response.defer()
            res = await db.quick_check()
            self.note = f"{Status.OK if res == 'ok' else Status.ERROR} Quick check: `{res}`"
            await self.refresh(interaction)

        async def do_full(interaction: discord.Interaction[Any]) -> None:
            await interaction.response.defer()
            res = await db.integrity_check()
            self.note = f"{Status.OK if res == 'ok' else Status.ERROR} Full integrity check: `{res}`"
            await self.refresh(interaction)

        async def to_restore(interaction: discord.Interaction[Any]) -> None:
            self.mode = "restore"
            await self.refresh(interaction)

        async def cancel_restore(interaction: discord.Interaction[Any]) -> None:
            db.cancel_restore()
            self.note = f"{Status.OK} Pending restore cancelled."
            await self._reload()
            await self.refresh(interaction)

        controls = [button("Back up now", do_backup), button("Quick check", do_check),
                    button("Full integrity check", do_full)]
        controls.append(button("Cancel pending restore", cancel_restore, style=discord.ButtonStyle.danger)
                        if s["restore_pending"] else button("Restore from backup", to_restore))
        box.add_item(row(*controls))
        self.add_item(box)


class Admin(commands.Cog, name="Framework"):
    """Bot-owner tools to manage the framework and its extensions."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="fw", description="Framework management (bot owner)", invoke_without_command=True)
    @owner_only()
    async def fw(self, ctx: commands.Context[ZDBFBot]) -> None:
        await send_group_help(ctx)

    @fw.command(name="sync", description="Sync slash commands with Discord")
    @app_commands.describe(mode="changed: only if something changed · force: always · server: instant copy to this "
                                "server for testing · clear-server: remove those copies")
    async def fw_sync(self, ctx: commands.Context[ZDBFBot],
                      mode: Literal["changed", "force", "server", "clear-server"] = "changed") -> None:
        await ctx.defer()
        tree = self.bot.tree
        if mode in ("server", "clear-server") and ctx.guild is None:
            await ctx.send(view=cards.error("Server only", f"`{mode}` has to be run inside a server."))
            return
        note = ""
        if mode == "server":
            assert ctx.guild is not None
            tree.copy_global_to(guild=ctx.guild)
            synced = await tree.sync(guild=ctx.guild)
            note = (f"\n{Status.WARN} Copied {len(synced)} commands to this server. They show up instantly but "
                    "appear twice here (server copy and global). Run `fw sync clear-server` when you are done testing.")
        elif mode == "clear-server":
            assert ctx.guild is not None
            tree.clear_commands(guild=ctx.guild)
            if ctx.guild.id in self.bot.config.settings.bot.dev_guild_ids:
                for command in self.bot.commands:
                    app = getattr(command, "app_command", None)
                    if app is not None and is_owner_only(command):
                        tree.add_command(app, guild=ctx.guild, override=True)
            synced = await tree.sync(guild=ctx.guild)
            note = f"\n{Status.OK} Removed the server copies. {len(synced)} server-only commands remain here."
        done = await self.bot.sync_commands(force=mode == "force")
        budget = self.bot.slash_command_count()
        body = "\n".join(f"**{k}** · {v} commands" for k, v in done.items()) or "Global commands were already up to date."
        await ctx.send(view=cards.success(
            "Slash commands synced",
            body + note + f"\n-# Top-level: {budget['top_level']}/{budget['limit']} · "
                          f"incl. subcommands: {budget['with_subcommands']}"))

    @fw.command(name="cache", description="File / prefix / permission cache statistics")
    async def fw_cache(self, ctx: commands.Context[ZDBFBot]) -> None:
        s = global_file_handler.get_cache_stats()
        box = cards.card(
            "Caches",
            "**Atomic file storage**\n" + cards.kv({
                "Entries": f"{s['cache_size']}/{s['max_cache_size']}", "Hit rate": f"{s['hit_rate']}%",
                "Reads / writes": f"{s['total_reads']:,} / {s['total_writes']:,}",
                "Failures (r/w)": f"{s['read_failures']} / {s['write_failures']}",
                "Locks": f"{s['active_locks']} ({s['locked_now']} held)", "TTL": f"{s['cache_ttl']}s",
            }),
            cards.sep(),
            "**Runtime caches**\n" + cards.kv({
                "Prefixes": f"{len(self.bot.prefix_cache)} (hits {self.bot.prefix_cache.hits})",
                "Permissions": f"{len(self.bot._perm_cache)} servers",
            }),
        )

        async def clear(interaction: discord.Interaction[Any]) -> None:
            n = global_file_handler.clear_all_cache()
            self.bot.prefix_cache.clear()
            self.bot._perm_cache.clear()
            await interaction.response.send_message(view=cards.success("Caches cleared", f"{n} file entries dropped."),
                                                    ephemeral=True)

        box.add_item(row(button("Clear all caches", clear, style=discord.ButtonStyle.danger)))
        view = BaseView(author_id=ctx.author.id)
        view.add_item(box)
        view.message = await ctx.send(view=view)

    @fw.command(name="db", description="Database statistics and maintenance")
    async def fw_db(self, ctx: commands.Context[ZDBFBot]) -> None:
        await DatabaseView(self.bot, await self.bot.db.stats(), ctx.author.id).send(ctx)

    @fw.command(name="integrity", description="Run a full system integrity check")
    async def fw_integrity(self, ctx: commands.Context[ZDBFBot]) -> None:
        await ctx.defer()
        checks: list[tuple[bool | None, str, str]] = []

        def add(ok: bool | None, name: str, detail: str) -> None:
            checks.append((True if ok else None if ok is None else False, name, detail))

        try:
            Config.parse(self.bot.config.path.read_text(encoding="utf-8"))
            add(True, "Configuration", f"`{self.bot.config.path}` is valid")
        except (ConfigError, OSError) as exc:
            add(False, "Configuration", cards.truncate(exc, 200))
        res = await self.bot.db.integrity_check()
        add(res == "ok", "Database", f"integrity: `{res}`")
        for label, path in (("Data directory", Path("data")), ("Log directory", Path(self.bot.config.settings.logging.directory)),
                            ("Extensions directory", self.bot.ext.directory)):
            path.mkdir(parents=True, exist_ok=True)
            add(os.access(path, os.W_OK), label, f"`{path}` writable")
        probe = Path("data/.integrity_probe.json")
        ok = await global_file_handler.atomic_write_json(probe, {"t": time.time()})
        back = await global_file_handler.atomic_read_json(probe, use_cache=False)
        probe.unlink(missing_ok=True)
        add(ok and back is not None, "Atomic storage", "write/read round-trip")
        add(self.bot.hooks.running, "Event hook worker", f"queue {self.bot.hooks.queue_size}")
        failed = self.bot.ext.failed
        add(not failed or None, "Extensions", f"{len(self.bot.extensions)} loaded, {len(failed)} failed")
        budget = self.bot.slash_command_count()
        add(budget["top_level"] < 90 or None, "Slash budget", f"{budget['top_level']}/100 top-level commands")
        intents = self.bot.intents
        add((intents.members and intents.message_content) or None, "Privileged intents",
            f"members={intents.members}, message_content={intents.message_content}")
        add(self.bot.latency < 0.5, "Gateway latency", f"{self.bot.latency * 1000:.0f} ms")
        disk = shutil.disk_usage(".")
        add(disk.free / disk.total > 0.05, "Disk space", f"{human_bytes(disk.free)} free of {human_bytes(disk.total)}")

        failures = sum(c[0] is False for c in checks)
        warnings = sum(c[0] is None for c in checks)
        lines = [f"{status_dot(state)} **{name}**  {detail}" for state, name, detail in checks]
        if failed:
            lines.append("")
            lines.append("**Failed extensions**")
            lines += [f"{Status.ERROR} `{self.bot.ext.short_name(m)}`  {cards.truncate(e, 200)}" for m, e in failed.items()]
        level = "error" if failures else "warning" if warnings else "success"
        await Paginator.from_lines(lines, per_page=14, title="Integrity check", accent=level,
                                   subtitle=f"{len(checks)} checks · {failures} failed · {warnings} warnings").send(ctx)

    @fw.command(name="cleanup", description="Clear caches, __pycache__ folders and old logs")
    async def fw_cleanup(self, ctx: commands.Context[ZDBFBot]) -> None:
        await ctx.defer()

        def sweep() -> int:
            removed = 0
            for base in (Path("extensions"), Path("zdbf"), Path("migrations")):
                for d in base.rglob("__pycache__") if base.exists() else ():
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
            return removed

        pycache = await asyncio.to_thread(sweep)
        files = global_file_handler.clear_all_cache()
        report = await self.bot.run_maintenance()
        await ctx.send(view=cards.success("Cleanup complete", cards.kv({
            "__pycache__ folders": pycache + report["pycache"], "File cache entries": files,
            "Expired cache entries": report["expired_cache"], "Old log files": report["old_logs"],
            "Closed legacy connections": report["legacy_connections"], "Database": "checkpointed and optimised"})))

    @fw.command(name="atomic-test", description="Test atomic file operations")
    async def fw_atomic_test(self, ctx: commands.Context[ZDBFBot]) -> None:
        await ctx.defer()
        path = Path("data/.atomic_test.json")
        results = []
        t = time.perf_counter()
        ok = await global_file_handler.atomic_write_json(path, {"n": 0})
        results.append(("Write", ok, (time.perf_counter() - t) * 1000))
        t = time.perf_counter()
        data = await global_file_handler.atomic_read_json(path, use_cache=False)
        results.append(("Read", data == {"n": 0}, (time.perf_counter() - t) * 1000))
        t = time.perf_counter()
        await global_file_handler.atomic_read_json(path)
        cached = await global_file_handler.atomic_read_json(path)
        results.append(("Cached read", cached == {"n": 0}, (time.perf_counter() - t) * 1000))
        t = time.perf_counter()
        await asyncio.gather(*(global_file_handler.atomic_write_json(path, {"n": i}) for i in range(25)))
        final = await global_file_handler.atomic_read_json(path, use_cache=False)
        results.append(("25 concurrent writes", isinstance(final, dict) and 0 <= final.get("n", -1) < 25,
                        (time.perf_counter() - t) * 1000))
        path.unlink(missing_ok=True)
        body = "\n".join(f"{Status.OK if ok else Status.ERROR} **{name}** · `{ms:.2f} ms`" for name, ok, ms in results)
        await ctx.send(view=cards.static(cards.card("Atomic storage test", body,
                                                    accent="success" if all(r[1] for r in results) else "error")))

    @fw.command(name="alerts", description="Route framework alerts to a channel")
    @app_commands.describe(system="Which system's alerts", channel="Target channel (leave empty to clear)")
    async def fw_alerts(self, ctx: commands.Context[ZDBFBot],
                        system: Literal["default", "errors", "diagnostics", "eventhooks", "plugins", "extensions",
                                        "shards", "cluster", "backup", "scheduler", "automations",
                                        "marketplace", "database", "dashboard"] | None = None,
                        channel: discord.TextChannel | None = None) -> None:
        if system is None:
            lines = []
            for s in ALERT_SYSTEMS:
                cid = self.bot.alerts.channels.get(s)
                fallback = self.bot.alerts.channels.get("default")
                lines.append(f"**{s}** → " + (f"<#{cid}>" if cid else f"<#{fallback}> *(default)*" if fallback else "*not set*"))
            await ctx.send(view=cards.info("Alert routing", "\n".join(lines)
                                           + "\n\nSet one with `/fw alerts system:<name> channel:#channel`."))
            return
        await self.bot.alerts.set_channel(system, channel.id if channel else None)
        await ctx.send(view=cards.success("Alert routing updated",
                                          f"**{system}** alerts → {channel.mention if channel else '*cleared*'}"))

    @fw.command(name="modules", description="Show or toggle built-in modules")
    @app_commands.describe(module="Module to toggle", enabled="Turn it on or off")
    async def fw_modules(self, ctx: commands.Context[ZDBFBot], module: str | None = None,
                         enabled: bool | None = None) -> None:
        if module is None or enabled is None:
            lines = []
            for key, mod in BUILTIN_MODULES.items():
                loaded = mod in self.bot.extensions
                on = self.bot.config.module_enabled(key)
                state = Status.OK if loaded else (Status.ERROR if on else Status.OFF)
                extra = "" if loaded or not on else f" - failed: {cards.truncate(self.bot.ext.failed.get(mod, 'not loaded'), 80)}"
                lines.append(f"{state} **{key}** · {'enabled' if on else 'disabled'}{extra}")
            await ctx.send(view=cards.info("Built-in modules", "\n".join(lines)
                                           + "\n\nToggle with `/fw modules module:<name> enabled:<true|false>`."))
            return
        if module not in BUILTIN_MODULES or module == "admin":
            await ctx.send(view=cards.error("Unknown module", f"`{module}` is not a toggleable module."))
            return
        await self.bot.config.set(f"modules.{module}", enabled)
        res = await (self.bot.ext.load(module, validate=False) if enabled else self.bot.ext.unload(module))
        if not res.ok and res.error not in ("already loaded", "not loaded"):
            await ctx.send(view=cards.error(f"Module {module}", res.error or "failed"))
            return
        await ctx.send(view=cards.success(f"Module {module} {'enabled' if enabled else 'disabled'}",
                                          "Saved as a runtime override (config.toml is untouched)."))

    @fw_modules.autocomplete("module")
    async def _module_ac(self, interaction: discord.Interaction[Any], current: str) -> list[app_commands.Choice[str]]:
        return [app_commands.Choice(name=k, value=k) for k in BUILTIN_MODULES if current.lower() in k and k != "admin"]

    @fw.command(name="shutdown", description="Shut the bot down")
    async def fw_shutdown(self, ctx: commands.Context[ZDBFBot]) -> None:
        view = await confirm(ctx, "Shut down?", "The bot will go offline until it is started again.",
                             confirm_label="Shut down")
        if view.value:
            await self.bot.close()

    @fw.group(name="config", description="Inspect and validate configuration", invoke_without_command=True)
    async def fw_config(self, ctx: commands.Context[ZDBFBot]) -> None:
        await send_group_help(ctx)

    @fw_config.command(name="validate", description="Validate config.toml and extension config sections")
    async def fw_config_validate(self, ctx: commands.Context[ZDBFBot]) -> None:
        validator: ConfigValidator | None = self.bot.get_cog("Config Validator")  # type: ignore[assignment]
        result = validator.validate() if validator else ValidationResult()
        try:
            Config.parse(self.bot.config.path.read_text(encoding="utf-8"))
        except ConfigError as exc:
            result.errors.insert(0, str(exc))
        lines = [f"{Status.ERROR} {e}" for e in result.errors] + [f"{Status.WARN} {w}" for w in result.warnings]
        lines += [f"{Status.OFF} {i}" for i in result.info]
        level = "error" if result.errors else "warning" if result.warnings else "success"
        title = "Config is valid" if result.is_valid else "Config has errors"
        await Paginator.from_lines(lines or [f"{Status.OK} No issues found."], per_page=15, title=title, accent=level, subtitle=str(self.bot.config.path)).send(ctx)

    @fw_config.command(name="schema", description="Show the config.toml schema")
    async def fw_config_schema(self, ctx: commands.Context[ZDBFBot]) -> None:
        pages = []
        for name, info in Settings.model_fields.items():
            model = info.annotation
            fields = getattr(model, "model_fields", {})
            lines = [f"### [{name}]"]
            for fname, f in fields.items():
                ann = getattr(f.annotation, "__name__", str(f.annotation)).replace("typing.", "")
                lines.append(f"`{fname}` · *{ann}* · default `{f.default!r}`"[:300])
            pages.append("\n".join(lines))
        validator: ConfigValidator | None = self.bot.get_cog("Config Validator")  # type: ignore[assignment]
        if validator and validator.extension_schemas:
            pages.append("### Extension sections\n" + "\n".join(
                f"`{ext}` → {', '.join(f'`[{k}]`' for k in schema)}" for ext, schema in validator.extension_schemas.items()))
        await Paginator(pages, title="Config schema").send(ctx)

    @fw_config.command(name="show", description="Show the effective configuration (secrets hidden)")
    @app_commands.describe(section="Only show one section, e.g. bot or backup")
    async def fw_config_show(self, ctx: commands.Context[ZDBFBot], section: str | None = None) -> None:
        data = _redact(self.bot.config.raw)
        if section:
            data = {section: data.get(section, "<not set>")}
        pages = [cards.codeblock(json.dumps({k: v}, indent=2, default=str)[:3500], "json") for k, v in data.items()]
        overrides = self.bot.config.overrides
        foot = f"{len(overrides)} runtime override section(s)" if overrides else "no runtime overrides"
        await Paginator(pages, title="Effective config", foot=foot).send(ctx)

    @fw_config.command(name="reload", description="Reload config.toml and .env without restarting")
    async def fw_config_reload(self, ctx: commands.Context[ZDBFBot]) -> None:
        from dotenv import load_dotenv

        load_dotenv(override=True)
        try:
            self.bot.config.reload()
        except ConfigError as exc:
            await ctx.send(view=cards.error("Reload failed - old config kept", cards.truncate(exc, 1500)))
            return
        self.bot.prefix_cache.clear()
        await ctx.send(view=cards.success("Config reloaded",
                                          "Prefixes, status rotation and module settings now use the new values.\n"
                                          "-# Intents, sharding and the database path need a restart."))

    @fw_config.command(name="set", description="Set a runtime override, e.g. backup.max_per_guild 50")
    @app_commands.describe(key="Dotted key", value="JSON value (true, 5, \"text\", [1,2])")
    async def fw_config_set(self, ctx: commands.Context[ZDBFBot], key: str, *, value: str) -> None:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        try:
            await self.bot.config.set(key, parsed)
        except ConfigError as exc:
            await ctx.send(view=cards.error("Invalid value", cards.truncate(exc, 1500)))
            return
        self.bot.prefix_cache.clear()
        await ctx.send(view=cards.success("Override saved", f"`{key}` = `{parsed!r}`"))

    @fw_config.command(name="unset", description="Remove a runtime override")
    async def fw_config_unset(self, ctx: commands.Context[ZDBFBot], key: str) -> None:
        removed = await self.bot.config.unset(key)
        self.bot.prefix_cache.clear()
        await ctx.send(view=(cards.success("Override removed", f"`{key}` uses config.toml again.") if removed
                             else cards.warning("No override", f"`{key}` had no runtime override.")))

    @commands.hybrid_group(name="ext", description="Load, unload and reload extensions (bot owner)",
                           invoke_without_command=True)
    @owner_only()
    async def ext(self, ctx: commands.Context[ZDBFBot]) -> None:
        await self.ext_list.callback(self, ctx)  # type: ignore[arg-type]

    async def _ext_autocomplete(self, interaction: discord.Interaction[Any],
                                current: str) -> list[app_commands.Choice[str]]:
        names = {self.bot.ext.short_name(m) for m in self.bot.ext.discover()}
        names |= {self.bot.ext.short_name(m) for m in self.bot.extensions if not m.startswith("zdbf.cogs.compat")}
        return [app_commands.Choice(name=n, value=n) for n in sorted(names) if current.lower() in n.lower()][:25]

    @ext.command(name="list", description="List loaded, failed and available extensions")
    async def ext_list(self, ctx: commands.Context[ZDBFBot]) -> None:
        mgr = self.bot.ext
        loaded = set(self.bot.extensions)
        lines = ["**Built-in modules**"]
        for key, mod in BUILTIN_MODULES.items():
            if mod in loaded:
                lines.append(f"{Status.OK} `{key}` · {mgr.load_times.get(key, 0):.0f} ms")
        lines.append("")
        lines.append("**Extensions**")
        available = mgr.discover()
        for mod in available:
            name = mgr.short_name(mod)
            meta = self.bot.plugins.get(name)
            if mod in loaded:
                version = f" v{meta.version}" if meta and meta.version != "unknown" else ""
                lines.append(f"{Status.OK} `{name}`{version} · {mgr.load_times.get(name, 0):.0f} ms")
            elif mod in mgr.failed:
                lines.append(f"{Status.ERROR} `{name}` · {cards.truncate(mgr.failed[mod], 90)}")
            else:
                lines.append(f"{Status.OFF} `{name}`  not loaded")
        if not available:
            lines.append(f"*No extensions in `{mgr.directory}/` yet - try `/marketplace browse`.*")
        await Paginator.from_lines(lines, per_page=20, title="Extensions",
                                   subtitle=f"{len(loaded)} modules loaded").send(ctx)

    @ext.command(name="load", description="Load an extension")
    @app_commands.autocomplete(name=_ext_autocomplete)
    async def ext_load(self, ctx: commands.Context[ZDBFBot], *, name: str) -> None:
        await _result_view([await self.bot.ext.load(name)], "Load extension").send(ctx)

    @ext.command(name="unload", description="Unload an extension")
    @app_commands.autocomplete(name=_ext_autocomplete)
    async def ext_unload(self, ctx: commands.Context[ZDBFBot], *, name: str) -> None:
        await _result_view([await self.bot.ext.unload(name)], "Unload extension").send(ctx)

    @ext.command(name="reload", description="Reload an extension (or 'all')")
    @app_commands.autocomplete(name=_ext_autocomplete)
    async def ext_reload(self, ctx: commands.Context[ZDBFBot], *, name: str) -> None:
        await ctx.defer()
        if name.lower() == "all":
            targets = [m for m in self.bot.extensions if not m.startswith(("zdbf.cogs.admin", "zdbf.cogs.compat"))]
            results = [await self.bot.ext.reload(m) for m in targets]
        else:
            results = [await self.bot.ext.reload(name)]
        await _result_view(results, "Reload").send(ctx)

    @ext.command(name="info", description="Metadata of a loaded extension")
    @app_commands.autocomplete(name=_ext_autocomplete)
    async def ext_info(self, ctx: commands.Context[ZDBFBot], *, name: str) -> None:
        plugins = self.bot.get_cog("Plugins")
        if plugins is not None:
            await plugins.plugin_info.callback(plugins, ctx, name=name)  # type: ignore[attr-defined]
            return
        await ctx.send(view=cards.warning("Plugins module disabled", "Enable it to see extension metadata."))


class ConfigValidator(commands.Cog, name="Config Validator"):
    """V1-compatible API for extensions to register config schemas."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.extension_schemas: dict[str, dict[str, Any]] = {}

    def register_extension_schema(self, extension_name: str, schema: dict[str, Any]) -> None:
        self.extension_schemas[extension_name] = schema

    def unregister_extension_schema(self, extension_name: str) -> None:
        self.extension_schemas.pop(extension_name, None)

    def validate(self) -> ValidationResult:
        result = ValidationResult()
        framework = set(Settings.model_fields)
        for ext_name, schema in self.extension_schemas.items():
            safe = {k: v for k, v in schema.items() if k not in framework}
            for k in set(schema) - set(safe):
                result.warnings.append(f"extension `{ext_name}` tried to redefine framework section `[{k}]`")
            data = {k: self.bot.config.raw.get(k) for k in safe if k in self.bot.config.raw}
            result.extend(validate_against(data, safe, warn_unknown=False))
        known = framework | {k for s in self.extension_schemas.values() for k in s}
        for key in self.bot.config.raw:
            if key not in known:
                result.info.append(f"section `[{key}]` has no registered schema")
        return result


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(Admin(bot))
    await bot.add_cog(ConfigValidator(bot))
