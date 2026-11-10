# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import io
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ...core.permissions import owner_only
from ...ui import (
    BaseView,
    Glyph,
    ListDetailView,
    Paginator,
    Status,
    button,
    cards,
    chunk_lines,
    confirm,
    respond,
    row,
    select,
)
from ...utils import human_bytes, human_duration
from .restore import Restorer, RestoreReport
from .snapshot import COMPONENTS, BackupEntry, BackupStorage, capture, diff

if TYPE_CHECKING:
    from ...core.bot import ZDBFBot

log = logging.getLogger("zdbf.backup")


def backup_authorized():
    async def predicate(ctx: commands.Context[ZDBFBot]) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator:
            return True
        raise commands.MissingPermissions(["administrator"])

    return commands.check(predicate)


def _when(iso: str) -> str:
    try:
        return cards.timestamp(dt.datetime.fromisoformat(iso), "f")
    except ValueError:
        return iso


def _entry_line(e: BackupEntry) -> str:
    c = e.counts
    tags = " · ".join(t for t in ("pinned" if e.pinned else "", "automatic" if e.automatic else "") if t)
    return (f"**{e.label}**  `{e.backup_id}`" + (f"  *{tags}*" if tags else "")
            + f"\n-# {_when(e.created_at)} · {c.get('roles', 0)} roles · {c.get('channels', 0)} channels · "
            f"{c.get('members', 0)} members · {human_bytes(e.size_bytes)}")


def report_pages(report: RestoreReport) -> list[list[Any]]:
    if report.dry_run:
        summary = cards.kv({"Would create": report.created, "Would update": report.updated,
                            "Already present": report.skipped, "Member role changes": report.members_changed,
                            "Roles added / removed": f"{report.roles_added} / {report.roles_removed}"})
        detail_title, detail = "Planned changes", [f"{Glyph.BULLET} {p}" for p in report.planned]
        if not detail:
            detail = ["*Nothing to create. The server already matches this backup.*"]
    else:
        summary = cards.kv({"Created": report.created, "Updated": report.updated, "Skipped": report.skipped,
                            "Failed": report.failed, "Members changed": report.members_changed,
                            "Roles added / removed": f"{report.roles_added} / {report.roles_removed}",
                            "Duration": human_duration(report.elapsed)})
        detail_title, detail = "Steps", [f"{Status.OK} {s}" for s in report.steps]
    problems = [f"{Status.ERROR} {e}" for e in report.errors]
    pages: list[list[Any]] = []
    for i, chunk in enumerate(chunk_lines(detail, per_page=15, max_chars=2400)):
        pages.append([summary, cards.sep(), f"**{detail_title}**\n{chunk}"] if i == 0 else [f"**{detail_title}**\n{chunk}"])
    pages += [[f"**Problems** · {len(problems)}\n{chunk}"] for chunk in chunk_lines(problems, per_page=15)] if problems else []
    return pages


def report_accent(report: RestoreReport) -> str:
    return "info" if report.dry_run else ("warning" if report.failed else "success")


class RestoreView(BaseView):
    def __init__(self, cog: Backup, guild: discord.Guild, entry: BackupEntry, snap: dict[str, Any],
                 author_id: int) -> None:
        super().__init__(author_id=author_id, timeout=600)
        self.cog = cog
        self.guild = guild
        self.entry = entry
        self.snap = snap
        available = set(snap.get("components") or COMPONENTS)
        self.available = [c for c in COMPONENTS if c in available]
        self.selected = {c for c in self.available if c != "server_images"}
        self.update_existing = False
        self.sync_roles = False
        self.armed = False
        self.result: Paginator | None = None
        self.closed: str | None = None
        self.running: str | None = None

    def build(self) -> None:
        self.clear_items()
        if self.result is not None:
            self.result.build()
            for item in list(self.result.children):
                self.add_item(item)
            return
        if self.closed is not None:
            self.add_item(cards.card(self.closed, "Nothing was changed.", accent="muted"))
            return
        if self.running is not None:
            self.add_item(cards.card("Restoring…", self.running, accent="warning",
                                     foot="Working through Discord's rate limits - large servers take a few minutes."))
            return
        e = self.entry
        box = cards.card(
            f"Restore {e.label}",
            f"Backup `{e.backup_id}` from {_when(e.created_at)}.\n"
            "Restores are additive: nothing in the server is deleted, and items are matched by name.",
            cards.sep(),
            cards.kv({"Components": ", ".join(COMPONENTS[c][1] for c in self.available if c in self.selected) or "none",
                      "Existing items": "updated to the backed-up settings" if self.update_existing
                      else "kept as they are (only missing items are created)",
                      "Member roles": "synchronised (roles not in the backup are removed)" if self.sync_roles
                      else "missing roles are added"}),
            ("-# Press Confirm restore to start." if self.armed else None),
            accent="error" if self.armed else "warning",
        )

        async def pick(interaction: discord.Interaction[Any]) -> None:
            self.selected = set(interaction.data.get("values", []))  # type: ignore[union-attr]
            self.armed = False
            await self.refresh(interaction)

        options = [discord.SelectOption(label=COMPONENTS[c][1], value=c, default=c in self.selected)
                   for c in self.available]
        box.add_item(row(select(options, pick, placeholder="Components to restore", min_values=0,
                                max_values=len(options))))

        async def toggle_update(interaction: discord.Interaction[Any]) -> None:
            self.update_existing = not self.update_existing
            self.armed = False
            await self.refresh(interaction)

        async def toggle_sync(interaction: discord.Interaction[Any]) -> None:
            self.sync_roles = not self.sync_roles
            self.armed = False
            await self.refresh(interaction)

        box.add_item(row(
            button(f"Update existing: {'On' if self.update_existing else 'Off'}", toggle_update,
                   style=discord.ButtonStyle.success if self.update_existing else discord.ButtonStyle.secondary),
            button(f"Sync member roles: {'On' if self.sync_roles else 'Off'}", toggle_sync,
                   style=discord.ButtonStyle.success if self.sync_roles else discord.ButtonStyle.secondary),
        ))
        box.add_item(row(
            button("Preview (dry run)", self._preview, style=discord.ButtonStyle.primary,
                   disabled=not self.selected),
            button("Confirm restore" if self.armed else "Restore", self._restore,
                   style=discord.ButtonStyle.danger if self.armed else discord.ButtonStyle.success,
                   disabled=not self.selected),
            button("Cancel", self._cancel),
        ))
        self.add_item(box)

    def _restorer(self, *, dry_run: bool, progress: Any = None) -> Restorer:
        return Restorer(self.cog.bot, self.guild, self.snap, set(self.selected), dry_run=dry_run,
                        update_existing=self.update_existing, sync_member_roles=self.sync_roles,
                        progress=progress, reason=f"Backup restore {self.entry.backup_id}")

    async def _preview(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        report = await self._restorer(dry_run=True).run()
        await Paginator(report_pages(report), title="Restore preview", accent=report_accent(report),
                        author_id=interaction.user.id).send(interaction, ephemeral=True)

    async def _restore(self, interaction: discord.Interaction[Any]) -> None:
        if not self.armed:
            self.armed = True
            await self.refresh(interaction)
            return
        lock = self.cog.lock(self.guild.id)
        if lock.locked():
            await interaction.response.send_message(view=cards.warning("Busy", "A backup or restore is already "
                                                                       "running for this server."), ephemeral=True)
            return
        self.running = "Starting…"
        await self.refresh(interaction)
        last_edit = float("-inf")

        async def progress(text: str) -> None:
            nonlocal last_edit
            done = "\n".join(f"{Status.OK} {s}" for s in report_steps[:-1])
            self.running = f"{done}\n{Status.WARN} {text}".strip()
            if time.monotonic() - last_edit > 2:
                last_edit = time.monotonic()
                await self.refresh(interaction)

        restorer = self._restorer(dry_run=False, progress=progress)
        report_steps = restorer.report.steps
        async with lock:
            report = await restorer.run()
        await self.cog.storage.audit(self.guild.id, "restore", interaction.user.id, self.entry.backup_id,
                                     f"{','.join(sorted(self.selected))} created={report.created} failed={report.failed}")
        self.running = None
        self.result = Paginator(report_pages(report), title="Restore complete", accent=report_accent(report))
        self.result.refresh = self.refresh  # type: ignore[method-assign]  # page buttons re-render this view
        await self.refresh(interaction)

    async def _cancel(self, interaction: discord.Interaction[Any]) -> None:
        self.closed = "Restore cancelled"
        await self.refresh(interaction)
        self.stop()


class Dashboard(ListDetailView[BackupEntry]):
    title = "Backup & restore"
    placeholder = "Open a backup"
    empty_text = "*No backups yet. Create the first one below.*"
    per_page = 5

    def __init__(self, cog: Backup, guild: discord.Guild, entries: list[BackupEntry], author_id: int) -> None:
        super().__init__(entries, author_id=author_id)
        self.cog = cog
        self.guild = guild

    async def reload(self) -> None:
        self.replace_items(await self.cog.storage.list(self.guild.id))

    def item_key(self, item: BackupEntry) -> str:
        return item.backup_id

    def item_line(self, item: BackupEntry) -> str:
        return _entry_line(item)

    def item_option(self, item: BackupEntry) -> discord.SelectOption:
        return discord.SelectOption(label=cards.truncate(item.label, 90), value=item.backup_id,
                                    description=f"{item.created_at[:16].replace('T', ' ')} · {human_bytes(item.size_bytes)}"
                                    + (" · pinned" if item.pinned else ""))

    def subtitle(self) -> str:
        total = sum(e.size_bytes for e in self.items)
        return f"{self.guild.name} · {len(self.items)} of {self.cog.settings.max_per_guild} backups · {human_bytes(total)}"

    def intro(self) -> list[Any]:
        g = self.guild
        return [cards.kv({"Roles": len(g.roles) - 1, "Channels": len(g.channels), "Emojis": len(g.emojis),
                          "Members": g.member_count}), cards.sep()]

    def list_controls(self) -> list[discord.ui.Item[Any]]:
        async def create(interaction: discord.Interaction[Any]) -> None:
            await interaction.response.defer()
            _ok, text = await self.cog.create_backup(self.guild, interaction.user.id, "Dashboard backup")
            self.note = text
            await self.reload()
            await self.refresh(interaction)

        async def refresh(interaction: discord.Interaction[Any]) -> None:
            await self.reload()
            await self.refresh(interaction)

        return [row(button("Create backup", create, style=discord.ButtonStyle.success), button("Refresh", refresh))]

    def detail(self, item: BackupEntry) -> discord.ui.Container[Any]:
        e, c = item, item.counts
        return cards.card(
            e.label,
            cards.kv({"ID": f"`{e.backup_id}`", "Created": _when(e.created_at),
                      "Created by": f"<@{e.created_by}>" if e.created_by else "automatic",
                      "Size": human_bytes(e.size_bytes), "Format": f"v{e.version}", "Checksum": f"`{e.checksum}`",
                      "Pinned": "yes" if e.pinned else "no"}),
            cards.sep(),
            cards.kv({"Roles": c.get("roles", 0), "Categories": c.get("categories", 0), "Channels": c.get("channels", 0),
                      "Emojis": c.get("emojis", 0), "Stickers": c.get("stickers", 0), "Members": c.get("members", 0)}),
            f"**Note**  {e.note}" if e.note else None,
            subtitle="Backup",
            accent="primary",
        )

    def detail_controls(self, item: BackupEntry) -> list[discord.ui.Item[Any]]:
        e = item

        async def restore(interaction: discord.Interaction[Any]) -> None:
            snap = await self.cog.storage.load(e)
            if snap is None:
                await interaction.response.send_message(view=cards.error("Unreadable", "The backup file is missing."),
                                                        ephemeral=True)
                return
            await RestoreView(self.cog, self.guild, e, snap, interaction.user.id).send(interaction)

        async def pin(interaction: discord.Interaction[Any]) -> None:
            await self.cog.storage.update(e, pinned=int(not e.pinned))
            await self.reload()
            await self.refresh(interaction)

        async def verify(interaction: discord.Interaction[Any]) -> None:
            ok, text = await self.cog.storage.verify(e)
            self.note = f"{Status.OK if ok else Status.ERROR} Verification: {text}"
            await self.refresh(interaction)

        async def compare(interaction: discord.Interaction[Any]) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            view = await self.cog.diff_view(self.guild, e, None)
            await view.send(interaction, ephemeral=True)

        async def delete(interaction: discord.Interaction[Any]) -> None:
            if e.pinned:
                await interaction.response.send_message(view=cards.warning("Pinned", "Unpin the backup first."),
                                                        ephemeral=True)
                return
            await self.cog.storage.delete(e, interaction.user.id)
            self.selected = None
            self.note = f"Deleted `{e.label}`."
            await self.reload()
            await self.refresh(interaction)

        return [button("Restore", restore, style=discord.ButtonStyle.success), button("Unpin" if e.pinned else "Pin", pin), button("Verify", verify), button("Compare with server", compare), button("Delete", delete, style=discord.ButtonStyle.danger)]


class Backup(commands.Cog, name="Backup"):
    """Full server snapshots: roles, channels, permissions, emojis, member roles and settings."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.storage = BackupStorage(bot.db)
        self._locks: dict[int, asyncio.Lock] = {}
        self._cooldowns: dict[int, float] = {}
        self._auto: asyncio.Task[None] | None = None

    @property
    def settings(self) -> Any:
        return self.bot.config.settings.backup

    def lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    async def cog_load(self) -> None:
        self._auto = asyncio.create_task(self._auto_loop(), name="zdbf-auto-backup")

    async def cog_unload(self) -> None:
        if self._auto:
            self._auto.cancel()

    async def create_backup(self, guild: discord.Guild, user_id: int, label: str, *,
                            components: set[str] | None = None, automatic: bool = False,
                            bypass_cooldown: bool = False) -> tuple[bool, str]:
        remaining = self.settings.cooldown_seconds - (time.monotonic() - self._cooldowns.get(guild.id, -1e9))
        if remaining > 0 and not bypass_cooldown:
            return False, f"Backup cooldown - try again in {human_duration(remaining)}."
        lock = self.lock(guild.id)
        if lock.locked():
            return False, f"{Status.WARN} A backup or restore is already running."
        async with lock:
            start = time.monotonic()
            snap = await capture(guild, self.bot, components)
            entry = await self.storage.save(guild.id, snap, label=label, user_id=user_id, automatic=automatic)
            self._cooldowns[guild.id] = time.monotonic()
            removed = await self.storage.enforce_limits(guild.id, self.settings.max_per_guild,
                                                        self.settings.retention_days)
        text = (f"{Status.OK} Created **{entry.label}** `{entry.backup_id}` in {time.monotonic() - start:.1f}s "
                f"({human_bytes(entry.size_bytes)})" + (f" · rotated {removed} old backup(s)" if removed else ""))
        return True, text

    async def _auto_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            await asyncio.sleep(600)
            for guild in list(self.bot.guilds):
                try:
                    schedule = await self.bot.db.get_setting(guild.id, "backup_schedule", None)
                    hours = (schedule or {}).get("interval_hours", self.settings.auto_interval_hours)
                    if not hours:
                        continue
                    entries = [e for e in await self.storage.list(guild.id) if e.automatic]
                    last = dt.datetime.fromisoformat(entries[0].created_at) if entries else None
                    if last and dt.datetime.now(dt.UTC) - last < dt.timedelta(hours=hours):
                        continue
                    _ok, text = await self.create_backup(guild, 0, "Automatic backup", automatic=True,
                                                        bypass_cooldown=True)
                    log.info("auto backup %s: %s", guild.id, text)
                except Exception as exc:
                    log.exception("auto backup failed for %s", guild.id)
                    await self.bot.alerts.send("backup", f"Automatic backup failed for `{guild.name}`: {exc}", "error")

    async def diff_view(self, guild: discord.Guild, a: BackupEntry, b: BackupEntry | None) -> BaseView:
        old = await self.storage.load(a)
        new = await self.storage.load(b) if b else await capture(guild, self.bot, {"roles", "categories", "channels",
                                                                                   "emojis", "stickers"})
        target = f"`{b.label}`" if b else "the current server"
        intro = f"`{a.label}` compared with {target}.\n-# Added = present now but not in the backup · Removed = " \
                "in the backup but gone now · Changed = settings differ"
        if old is None or new is None:
            return Paginator(["One of the backups could not be read."], title="Backup comparison", accent="error")
        pages: list[list[Any]] = []
        for section, change in diff(old, new).items():
            lines = ([f"{Status.OK} added  {n}" for n in change["added"]]
                     + [f"{Status.ERROR} removed  {n}" for n in change["removed"]]
                     + [f"{Status.WARN} changed  {n}" for n in change["changed"]])
            for chunk in chunk_lines(lines, per_page=20, max_chars=2400) if lines else []:
                pages.append([intro, cards.sep(), f"**{section.title()}** · {len(lines)} difference(s)\n{chunk}"])
        if not pages:
            pages = [[intro, cards.sep(), f"{Status.OK} No differences."]]
        return Paginator(pages, title="Backup comparison")

    async def _backup_ac(self, interaction: discord.Interaction[Any], current: str) -> list[app_commands.Choice[str]]:
        entries = await self.storage.list(interaction.guild_id or 0)
        return [app_commands.Choice(name=f"{e.label} · {e.created_at[:16].replace('T', ' ')} ({e.backup_id})"[:100],
                                    value=e.backup_id)
                for e in entries if current.lower() in e.label.lower() or current in e.backup_id][:25]

    async def _get(self, ctx: commands.Context[ZDBFBot], backup_id: str) -> BackupEntry | None:
        assert ctx.guild is not None
        entry = await self.storage.get(ctx.guild.id, backup_id.strip())
        if entry is None:
            await ctx.send(view=cards.error("Backup not found", f"No backup `{backup_id}` in this server."))
        return entry

    @commands.hybrid_group(name="backup", fallback="dashboard", description="Server backup & restore",
                           invoke_without_command=True)
    @commands.guild_only()
    @backup_authorized()
    async def backup(self, ctx: commands.Context[ZDBFBot]) -> None:
        assert ctx.guild is not None
        await Dashboard(self, ctx.guild, await self.storage.list(ctx.guild.id), ctx.author.id).send(ctx)

    @backup.command(name="create", description="Create a full backup now")
    @app_commands.describe(label="A name for this backup")
    @commands.guild_only()
    @backup_authorized()
    async def backup_create(self, ctx: commands.Context[ZDBFBot], *, label: str = "Manual backup") -> None:
        assert ctx.guild is not None
        await ctx.defer()
        ok, text = await self.create_backup(ctx.guild, ctx.author.id, label)
        await ctx.send(view=(cards.success if ok else cards.warning)("Backup" if ok else "Backup not created", text))

    @backup.command(name="restore", description="Restore from a backup (choose components, preview first)")
    @app_commands.autocomplete(backup_id=_backup_ac)
    @commands.guild_only()
    @backup_authorized()
    async def backup_restore(self, ctx: commands.Context[ZDBFBot], backup_id: str) -> None:
        assert ctx.guild is not None
        entry = await self._get(ctx, backup_id)
        if entry is None:
            return
        snap = await self.storage.load(entry)
        if snap is None:
            await ctx.send(view=cards.error("Unreadable backup", "Run `/backup verify` to check it."))
            return
        await RestoreView(self, ctx.guild, entry, snap, ctx.author.id).send(ctx)

    @backup.command(name="list", description="All backups of this server")
    @commands.guild_only()
    @backup_authorized()
    async def backup_list(self, ctx: commands.Context[ZDBFBot]) -> None:
        assert ctx.guild is not None
        entries = await self.storage.list(ctx.guild.id)
        await Paginator.from_lines([_entry_line(e) for e in entries] or ["*No backups yet.*"], per_page=8,
                                   title="Backups",
                                   subtitle=f"{len(entries)}/{self.settings.max_per_guild} · "
                                            f"{human_bytes(sum(e.size_bytes for e in entries))}").send(ctx)

    @backup.command(name="view", description="Details of one backup")
    @app_commands.autocomplete(backup_id=_backup_ac)
    @commands.guild_only()
    @backup_authorized()
    async def backup_view(self, ctx: commands.Context[ZDBFBot], backup_id: str) -> None:
        assert ctx.guild is not None
        entry = await self._get(ctx, backup_id)
        if entry:
            view = Dashboard(self, ctx.guild, await self.storage.list(ctx.guild.id), ctx.author.id)
            view.selected = entry
            await view.send(ctx)

    @backup.command(name="delete", description="Delete a backup")
    @app_commands.autocomplete(backup_id=_backup_ac)
    @commands.guild_only()
    @backup_authorized()
    async def backup_delete(self, ctx: commands.Context[ZDBFBot], backup_id: str) -> None:
        entry = await self._get(ctx, backup_id)
        if entry is None:
            return
        if entry.pinned:
            await ctx.send(view=cards.warning("Pinned", "Unpin it first with `/backup pin`."))
            return
        view = await confirm(ctx, "Delete backup?", f"`{entry.label}` ({entry.backup_id}) is removed permanently.",
                             confirm_label="Delete")
        if view.value:
            await self.storage.delete(entry, ctx.author.id)

    @backup.command(name="pin", description="Pin / unpin a backup (pinned backups are never rotated)")
    @app_commands.autocomplete(backup_id=_backup_ac)
    @commands.guild_only()
    @backup_authorized()
    async def backup_pin(self, ctx: commands.Context[ZDBFBot], backup_id: str) -> None:
        entry = await self._get(ctx, backup_id)
        if entry:
            await self.storage.update(entry, pinned=int(not entry.pinned))
            await self.storage.audit(entry.guild_id, "unpin" if entry.pinned else "pin", ctx.author.id, entry.backup_id)
            await ctx.send(view=cards.success("Unpinned" if entry.pinned else "Pinned", f"`{entry.label}`"))

    @backup.command(name="note", description="Attach a note to a backup")
    @app_commands.autocomplete(backup_id=_backup_ac)
    @commands.guild_only()
    @backup_authorized()
    async def backup_note(self, ctx: commands.Context[ZDBFBot], backup_id: str, *, note: str) -> None:
        entry = await self._get(ctx, backup_id)
        if entry:
            await self.storage.update(entry, note=note[:500])
            await ctx.send(view=cards.success("Note saved", f"`{entry.label}`: {note[:500]}"))

    @backup.command(name="verify", description="Check a backup's integrity")
    @app_commands.autocomplete(backup_id=_backup_ac)
    @commands.guild_only()
    @backup_authorized()
    async def backup_verify(self, ctx: commands.Context[ZDBFBot], backup_id: str) -> None:
        entry = await self._get(ctx, backup_id)
        if entry:
            ok, text = await self.storage.verify(entry)
            await ctx.send(view=(cards.success if ok else cards.error)(f"Verify {entry.label}", text))

    @backup.command(name="diff", description="Compare a backup with another backup or the current server")
    @app_commands.autocomplete(backup_id=_backup_ac, other=_backup_ac)
    @commands.guild_only()
    @backup_authorized()
    async def backup_diff(self, ctx: commands.Context[ZDBFBot], backup_id: str, other: str | None = None) -> None:
        assert ctx.guild is not None
        a = await self._get(ctx, backup_id)
        b = await self._get(ctx, other) if other else None
        if a is None or (other and b is None):
            return
        await ctx.defer()
        await (await self.diff_view(ctx.guild, a, b)).send(ctx)

    @backup.command(name="schedule", description="Automatic backups every N hours (0 = off)")
    @commands.guild_only()
    @backup_authorized()
    async def backup_schedule(self, ctx: commands.Context[ZDBFBot],
                              hours: app_commands.Range[int, 0, 720] | None = None) -> None:
        assert ctx.guild is not None
        if hours is None:
            current = await self.bot.db.get_setting(ctx.guild.id, "backup_schedule", None)
            value = (current or {}).get("interval_hours", self.settings.auto_interval_hours)
            await ctx.send(view=cards.info("Automatic backups",
                                           f"Every **{value} h**" if value else "Automatic backups are **off**."))
            return
        await self.bot.db.set_setting(ctx.guild.id, "backup_schedule", {"interval_hours": hours})
        await self.storage.audit(ctx.guild.id, "schedule", ctx.author.id, None, f"{hours}h")
        await ctx.send(view=cards.success("Automatic backups",
                                          f"Every **{hours} h**." if hours else "Turned **off**."))

    @backup.command(name="audit", description="Who created, restored or deleted backups")
    @commands.guild_only()
    @backup_authorized()
    async def backup_audit(self, ctx: commands.Context[ZDBFBot]) -> None:
        assert ctx.guild is not None
        rows = await self.storage.audit_log(ctx.guild.id, 100)
        lines = [f"**{r['action'].title()}**  {_when(r['created_at'])} by "
                 f"{'<@' + str(r['user_id']) + '>' if r['user_id'] else 'automation'}"
                 + (f" · `{r['backup_id']}`" if r["backup_id"] else "") + (f"\n-# {r['details']}" if r["details"] else "")
                 for r in rows]
        await Paginator.from_lines(lines or ["*Nothing yet.*"], per_page=10, title="Backup audit log").send(ctx)

    @backup.command(name="export", description="Download a backup as JSON (bot owner)")
    @app_commands.autocomplete(backup_id=_backup_ac)
    @commands.guild_only()
    @owner_only()
    async def backup_export(self, ctx: commands.Context[ZDBFBot], backup_id: str) -> None:
        entry = await self._get(ctx, backup_id)
        if entry is None:
            return
        snap = await self.storage.load(entry)
        if snap is None:
            await ctx.send(view=cards.error("Unreadable backup", "The file is missing."))
            return
        raw = json.dumps(snap, indent=2, default=str).encode()
        name = f"backup-{entry.guild_id}-{entry.backup_id}.json"
        if len(raw) > 8 * 1024 * 1024:
            raw, name = gzip.compress(raw), name + ".gz"
        file = discord.File(io.BytesIO(raw), filename=name)
        box = cards.card("Backup export", f"`{entry.label}` · {human_bytes(len(raw))}")
        box.add_item(discord.ui.File(f"attachment://{name}"))
        await respond(ctx, cards.static(box), ephemeral=True, files=[file])

    @backup.command(name="stats", description="Backup statistics across all servers (bot owner)")
    @owner_only()
    async def backup_stats(self, ctx: commands.Context[ZDBFBot]) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT guild_id, COUNT(*) AS n, SUM(size_bytes) AS size, SUM(pinned) AS pinned, MAX(created_at) AS last "
            "FROM backups GROUP BY guild_id ORDER BY size DESC")
        total_n = sum(r["n"] for r in rows)
        total_size = sum(r["size"] or 0 for r in rows)
        lines = [f"**{(g.name if (g := self.bot.get_guild(r['guild_id'])) else r['guild_id'])}** · {r['n']} backups · "
                 f"{human_bytes(r['size'] or 0)} · {r['pinned'] or 0} pinned · last {_when(r['last'])}" for r in rows]
        await Paginator.from_lines(lines or ["*No backups anywhere yet.*"], per_page=10, title="Backup statistics", subtitle=f"{total_n} backups · {human_bytes(total_size)} · "
                                                               f"{len(rows)} servers").send(ctx)
