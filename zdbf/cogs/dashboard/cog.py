# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import logging
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ...core.config import ConfigError
from ...core.permissions import owner_only
from ...ui import BaseView, Paginator, Status, button, cards, confirm, respond, row
from ...utils import human_bytes, human_duration
from .actions import Dispatcher, load_all
from .approvals import ApprovalManager
from .audit import AuditLog
from .capabilities import CATALOGUE, Policy
from .client import DashboardClient, LinkError, pair
from .export import ARCHIVE_ROOT, build_archive, new_setup_key
from .link import DATA_DIR, Link, LinkStore
from .logtail import TOPIC as LOG_TOPIC
from .logtail import LogTail, redactor
from .messages import serialize_message
from .panels import panels
from .protocol import PUSH_PATH, VERSION, ProtocolError, normalize_code, normalize_url
from .sandbox import Sandbox
from .state import StateHub

if TYPE_CHECKING:
    from ...core.bot import ZDBFBot

__all__ = ["Dashboard"]

log = logging.getLogger("zdbf.dashboard")
ATTACH_LIMIT = 8 * 1024 * 1024
SETUP_STEPS = (
    "1. Upload the contents of the `{root}` folder to your web host (FTP or the host's file manager).\n"
    "2. Open `https://your-site/your-folder/setup.php`, enter the setup key and follow the steps.\n"
    "3. Copy the pairing command from the last step and run it here.\n"
    "-# The website can run anywhere. The bot only makes outgoing HTTPS requests to it."
)


class CapabilityView(BaseView):
    def __init__(self, cog: Dashboard, author_id: int) -> None:
        super().__init__(author_id=author_id, timeout=600)
        self.cog = cog
        self.note: str | None = None

    async def _save(self, interaction: discord.Interaction[Any], key: str, value: Any, note: str) -> None:
        try:
            await self.cog.bot.config.set(f"dashboard.{key}", value)
        except ConfigError as exc:
            self.note = f"{Status.ERROR} {cards.truncate(exc, 300)}"
        else:
            self.note = f"{Status.OK} {note}"
            self.cog.policy_changed()
        await self.refresh(interaction)

    def build(self) -> None:
        self.clear_items()
        policy = self.cog.policy
        lines = []
        for cap in CATALOGUE:
            on = cap.name in policy.enabled
            dot = Status.OK if on else Status.OFF
            flags = []
            if cap.dangerous:
                flags.append("dangerous")
            if cap.name in policy.approval:
                flags.append("needs approval")
            lines.append(f"{dot} **{cap.name}**  {cap.description}" + (f"  -# {', '.join(flags)}" if flags else ""))
        box = cards.card(
            "Dashboard capabilities",
            "\n".join(lines),
            self.note,
            subtitle="What the website may ask the bot to do. Only you can change this, and only here or in config.toml.",
            accent="warning" if policy.locked else "primary",
            foot="Locked: view only" if policy.locked else None,
        )

        async def pick_enabled(interaction: discord.Interaction[Any]) -> None:
            chosen = set(interaction.data.get("values", []))  # type: ignore[union-attr]
            await self._save(interaction, "capabilities", [c.name for c in CATALOGUE if c.name in chosen],
                             f"{len(chosen)} capabilities are on.")

        async def pick_approval(interaction: discord.Interaction[Any]) -> None:
            chosen = set(interaction.data.get("values", []))  # type: ignore[union-attr]
            await self._save(interaction, "approval", [c.name for c in CATALOGUE if c.name in chosen],
                             f"{len(chosen)} capabilities need approval.")

        async def toggle_lock(interaction: discord.Interaction[Any]) -> None:
            locked = not self.cog.policy.locked
            await self._save(interaction, "locked", locked,
                             "The link is view-only now." if locked else "The link is unlocked.")

        enabled: discord.ui.Select[Any] = discord.ui.Select(
            placeholder="Capabilities that are on", min_values=0, max_values=len(CATALOGUE),
            options=[discord.SelectOption(label=c.name, value=c.name, description=c.description[:100],
                                          default=c.name in policy.enabled) for c in CATALOGUE])
        enabled.callback = pick_enabled  # type: ignore[method-assign]
        approval: discord.ui.Select[Any] = discord.ui.Select(
            placeholder="Capabilities that wait for your approval", min_values=0, max_values=len(CATALOGUE),
            options=[discord.SelectOption(label=c.name, value=c.name, description=c.description[:100],
                                          default=c.name in policy.approval) for c in CATALOGUE])
        approval.callback = pick_approval  # type: ignore[method-assign]
        box.add_item(row(enabled))
        box.add_item(row(approval))
        box.add_item(row(button("Unlock" if policy.locked else "Lock to view-only", toggle_lock,
                                style=discord.ButtonStyle.success if policy.locked else discord.ButtonStyle.danger)))
        self.add_item(box)


class Dashboard(commands.Cog, name="Dashboard"):
    """Link to the ZDBF Dashboard web control panel (bot owner)."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.store = LinkStore()
        self.link: Link | None = None
        self.client: DashboardClient | None = None
        self.audit = AuditLog(bot.db)
        self.approvals = ApprovalManager(bot)
        self.dispatcher = Dispatcher(self)
        self.state = StateHub(self)
        self.logtail: LogTail | None = None
        self._pair_lock = asyncio.Lock()

    @property
    def settings(self) -> Any:
        return self.bot.config.settings.dashboard

    @property
    def policy(self) -> Policy:
        return Policy(self.settings)

    @property
    def sandbox(self) -> Sandbox:
        return Sandbox(Path.cwd(), self.settings.file_roots, max_bytes=self.settings.max_file_kb * 1024)

    async def cog_load(self) -> None:
        load_all()
        self._attach_logs()
        self.bot.hooks.register("extension_unloaded", self._extension_unloaded)
        self.link = await asyncio.to_thread(self.store.load)
        if self.link is not None:
            self._start(self.link)
            log.info("dashboard link configured for %s", self.link.url)
        else:
            log.info("dashboard module loaded - not paired yet (run /dashboard export, then /dashboard pair)")

    async def cog_unload(self) -> None:
        if self.logtail is not None:
            self.logtail.detach()
            self.logtail = None
        await self._stop()

    async def _extension_unloaded(self, *, extension_name: str = "", **_: Any) -> None:
        if extension_name and panels.unregister_module(extension_name):
            self.policy_changed()

    def _attach_logs(self) -> None:
        secrets = self.bot.config.secrets
        level = logging.DEBUG if self.bot.config.settings.logging.level == "DEBUG" else logging.INFO
        self.logtail = LogTail(self._publish_log, redactor([secrets.token, secrets.ipc_secret]), level)
        self.logtail.attach(asyncio.get_running_loop())

    def _publish_log(self, entry: dict[str, Any]) -> None:
        if self.policy.allows("logs"):
            self.emit(LOG_TOPIC, entry)

    def _start(self, link: Link) -> None:
        self.client = DashboardClient(self, link)
        self.client.start()

    async def _stop(self) -> None:
        if self.client is not None:
            await self.client.stop()
            self.client = None

    async def post_result(self, result: dict[str, Any]) -> None:
        if self.client is not None:
            await self.client.post_result(result)

    def emit(self, topic: str, data: Any) -> None:
        if self.client is not None and self.client.watching(topic):
            self.client.emit(topic, data)

    def on_watch_changed(self) -> None:
        return None

    def _chat_watched(self, channel_id: int) -> bool:
        client = self.client
        return client is not None and client.watching(f"chat.{channel_id}") and self.policy.allows("chat.read")

    def _me(self) -> int | None:
        return self.bot.user.id if self.bot.user else None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if self._chat_watched(message.channel.id):
            self.emit(f"chat.{message.channel.id}", {"type": "message", "message": serialize_message(message, self._me())})

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        if self._chat_watched(payload.channel_id):
            self.emit(f"chat.{payload.channel_id}", {"type": "edit", "message": serialize_message(payload.message, self._me())})

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if self._chat_watched(payload.channel_id):
            self.emit(f"chat.{payload.channel_id}", {"type": "delete", "ids": [str(payload.message_id)]})

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        if self._chat_watched(payload.channel_id):
            self.emit(f"chat.{payload.channel_id}", {"type": "delete", "ids": [str(i) for i in payload.message_ids]})

    def _reaction(self, payload: discord.RawReactionActionEvent, delta: int) -> None:
        if not self._chat_watched(payload.channel_id):
            return
        emoji = payload.emoji
        self.emit(f"chat.{payload.channel_id}", {
            "type": "reaction", "id": str(payload.message_id), "delta": delta, "me": payload.user_id == self._me(),
            "emoji": str(emoji), "emoji_id": str(emoji.id) if emoji.id else None, "name": emoji.name,
            "animated": bool(emoji.animated),
        })

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        self._reaction(payload, 1)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        self._reaction(payload, -1)

    @commands.Cog.listener()
    async def on_raw_reaction_clear(self, payload: discord.RawReactionClearEvent) -> None:
        if self._chat_watched(payload.channel_id):
            self.emit(f"chat.{payload.channel_id}", {"type": "reactions_cleared", "id": str(payload.message_id)})

    def policy_changed(self) -> None:
        if self.policy.locked:
            self.approvals.clear_grants()
        if self.client is not None:
            self.client.wake(force_state=True)

    def _state_line(self) -> tuple[str, str]:
        client = self.client
        if self.link is None or client is None:
            return Status.OFF, "Not paired"
        if client.broken:
            return Status.ERROR, "Stopped - pair again"
        if client.connected:
            return Status.OK, "Connected" + (" · someone is watching" if client.watch_active else " · idle")
        if client.last_ok:
            return Status.WARN, f"Reconnecting ({cards.truncate(client.last_error or 'no answer', 80)})"
        return Status.WARN, f"Connecting ({cards.truncate(client.last_error or 'waiting for the bot to be ready', 80)})"

    def status_card(self) -> discord.ui.Container[Any]:
        policy = self.policy
        dot, state = self._state_line()
        client = self.client
        if self.link is None:
            return cards.card(
                "ZDBF Dashboard", f"{Status.OFF} Not paired with a website yet.", cards.sep(),
                SETUP_STEPS.format(root=ARCHIVE_ROOT),
                subtitle="Start with `/dashboard export` to get the files.", accent="muted")
        pairs: dict[str, Any] = {
            "Website": f"<{self.link.url}>",
            "Link": f"{dot} {state}",
            "Paired": cards.timestamp(self.link.paired_at, "R"),
        }
        if client is not None:
            pairs["Last contact"] = cards.timestamp(client.last_ok, "R") if client.last_ok else "never"
            if client.round_trip_ms is not None:
                pairs["Round trip"] = f"{client.round_trip_ms:.0f} ms"
            pairs["Held requests"] = "yes" if client.hold_ok else "no, short polling"
            pairs["Requests"] = f"{client.stats['requests']:,} ({client.stats['failures']:,} failed)"
            pairs["Commands received"] = f"{client.stats['commands']:,}"
        pairs["Capabilities"] = f"{len(policy.enabled)} of {len(CATALOGUE)} on, {len(policy.approval & policy.enabled)} need approval"
        pairs["Approvals waiting"] = self.approvals.pending
        if policy.locked:
            pairs["Lock"] = f"{Status.WARN} view only"
        return cards.card("ZDBF Dashboard", cards.kv(pairs),
                          accent="error" if client and client.broken else "warning" if policy.locked else "primary",
                          foot="The bot connects out to the website. No port is opened on this machine.")

    @commands.hybrid_group(name="dashboard", description="ZDBF Dashboard web control panel (bot owner)",
                           invoke_without_command=True)
    @owner_only()
    async def dashboard(self, ctx: commands.Context[ZDBFBot]) -> None:
        await self.dashboard_status.callback(self, ctx)  # type: ignore[arg-type]

    @dashboard.command(name="status", description="Link state, last contact and capabilities")
    async def dashboard_status(self, ctx: commands.Context[ZDBFBot]) -> None:
        await ctx.send(view=cards.static(self.status_card()), ephemeral=True)

    async def _private(self, ctx: commands.Context[ZDBFBot], view: discord.ui.LayoutView,
                       files: list[discord.File] | None = None) -> None:
        if ctx.interaction is not None or ctx.guild is None:
            await respond(ctx, view, ephemeral=True, files=files)
            return
        try:
            await ctx.author.send(view=view, files=files or [], allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            await ctx.send(view=cards.error("Could not send you a DM", "This answer contains a secret. Allow direct "
                                            "messages from the bot, or use the slash command, and try again."))
            return
        await ctx.send(view=cards.info("Sent to your DMs", "The answer contains a secret, so it was not posted here."))

    @dashboard.command(name="export", description="Build the folder you upload to your web host")
    async def dashboard_export(self, ctx: commands.Context[ZDBFBot]) -> None:
        await ctx.defer(ephemeral=True)
        target = DATA_DIR / f"{ARCHIVE_ROOT}.zip"
        key = new_setup_key()
        try:
            count, size = await asyncio.to_thread(build_archive, target, key)
        except FileNotFoundError:
            await ctx.send(view=cards.error(
                "Dashboard files not found",
                "This installation has no `dashboard/` folder next to the `zdbf` package. "
                f"Download it from <{self.bot.repo_url}> and put it beside `zdbf/`."), ephemeral=True)
            return
        attach = size <= ATTACH_LIMIT
        box = cards.card(
            "Dashboard files ready",
            cards.kv({"Files": count, "Size": human_bytes(size), "Setup key": f"`{key}`"}),
            f"**Saved on the bot host as**\n`{target.resolve().as_posix()}`",
            cards.sep(),
            SETUP_STEPS.format(root=ARCHIVE_ROOT),
            "-# The setup key belongs to this archive. Whoever has it can finish the setup, so keep it to yourself."
            + ("\n-# The archive is attached below." if attach else
               "\n-# The archive is too large to attach here. Take it from the path above."),
            subtitle="Requires PHP 8.1 or newer with SQLite or MySQL/MariaDB.",
            accent="success",
        )
        files = None
        if attach:
            box.add_item(discord.ui.File(f"attachment://{target.name}"))
            files = [discord.File(target, filename=target.name)]
        await self._private(ctx, cards.static(box), files)

    @dashboard.command(name="pair", description="Connect this bot to your uploaded dashboard")
    @app_commands.describe(url="Address of the dashboard, for example https://example.com/dashboard",
                           code="The pairing code shown by the dashboard")
    async def dashboard_pair(self, ctx: commands.Context[ZDBFBot], url: str, *, code: str) -> None:
        await ctx.defer(ephemeral=True)
        if ctx.interaction is None and ctx.guild is not None:
            with contextlib.suppress(discord.HTTPException):
                await ctx.message.delete()
        assert self.bot.user is not None
        try:
            base = normalize_url(url)
            clean = normalize_code(code)
        except ProtocolError as exc:
            await ctx.send(view=cards.error("Cannot pair", str(exc)), ephemeral=True)
            return
        async with self._pair_lock:
            try:
                link = await pair(base, clean, str(self.bot.user.id))
            except LinkError as exc:
                await ctx.send(view=cards.error("Pairing failed", str(exc)), ephemeral=True)
                return
            await self._stop()
            await asyncio.to_thread(self.store.save, link)
            self.link = link
            self.state.reset()
            self._start(link)
        await self.audit.record(action="pair", capability="-", outcome="ok",
                                user={"id": ctx.author.id, "name": str(ctx.author)}, detail=base)
        policy = self.policy
        await ctx.send(view=cards.success(
            "Dashboard paired",
            f"This bot now reports to <{base}>.\n"
            f"{len(policy.enabled)} capabilities are on. Dangerous ones stay off until you enable them with "
            "`/dashboard capabilities`.\n-# The shared secret was derived on both sides and never sent."),
            ephemeral=True)

    @dashboard.command(name="capabilities", description="Choose what the website may do, and what needs approval")
    async def dashboard_capabilities(self, ctx: commands.Context[ZDBFBot]) -> None:
        await CapabilityView(self, ctx.author.id).send(ctx, ephemeral=True)

    @dashboard.command(name="lock", description="Switch the dashboard link to view-only, or back")
    @app_commands.describe(locked="True = view only, false = unlock")
    async def dashboard_lock(self, ctx: commands.Context[ZDBFBot], locked: bool = True) -> None:
        await self.bot.config.set("dashboard.locked", locked)
        self.policy_changed()
        await self.audit.record(action="lock" if locked else "unlock", capability="-", outcome="ok",
                                user={"id": ctx.author.id, "name": str(ctx.author)})
        await ctx.send(view=(cards.warning("Dashboard locked", "The website can only read now. Nothing it asks for "
                                           "is run until you unlock it with `/dashboard lock false`.")
                             if locked else cards.success("Dashboard unlocked", "Enabled capabilities work again.")),
                       ephemeral=True)

    @dashboard.command(name="unpair", description="Disconnect this bot from the dashboard")
    async def dashboard_unpair(self, ctx: commands.Context[ZDBFBot]) -> None:
        if self.link is None:
            await ctx.send(view=cards.info("Not paired", "This bot is not connected to a dashboard."), ephemeral=True)
            return
        view = await confirm(ctx, "Unpair the dashboard?",
                             f"The bot stops talking to <{self.link.url}> and forgets the shared secret.",
                             confirm_label="Unpair", ephemeral=True)
        if not view.value:
            return
        told = await self.client.unpair() if self.client is not None else False
        await self._stop()
        await asyncio.to_thread(self.store.delete)
        url, self.link = self.link.url, None
        await self.audit.record(action="unpair", capability="-", outcome="ok",
                                user={"id": ctx.author.id, "name": str(ctx.author)}, detail=url)
        await ctx.send(view=cards.success(
            "Dashboard unpaired",
            "The website was told to forget this bot." if told else
            "The website could not be reached. Remove the bot there too, under Settings, if it still exists."),
            ephemeral=True)

    @dashboard.command(name="recover", description="Get a code to reset a lost owner password on the website")
    async def dashboard_recover(self, ctx: commands.Context[ZDBFBot]) -> None:
        if self.link is None or self.client is None:
            await ctx.send(view=cards.info("Not paired", "This bot is not connected to a dashboard."), ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        raw = base64.b32encode(secrets.token_bytes(15)).decode()
        code = "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))
        digest = hashlib.sha256(raw.encode()).hexdigest()
        try:
            await self.client.call(PUSH_PATH, {"v": VERSION, "recover": {"hash": digest, "ttl": 900}}, timeout=20)
        except (LinkError, ProtocolError, OSError, TimeoutError) as exc:
            await ctx.send(view=cards.error("The website could not be reached", cards.truncate(exc, 300)),
                           ephemeral=True)
            return
        await self.audit.record(action="recover", capability="-", outcome="ok",
                                user={"id": ctx.author.id, "name": str(ctx.author)}, detail=self.link.url)
        await self._private(ctx, cards.static(cards.card(
            "Recover an owner account",
            f"Open <{self.link.url}/recover.php> and enter this code within 15 minutes:",
            cards.codeblock(code),
            "-# It works once, for an account with the Owner role. Running this command again replaces the code.",
            accent="warning")))

    @dashboard.command(name="audit", description="Recent actions the dashboard asked the bot to run")
    async def dashboard_audit(self, ctx: commands.Context[ZDBFBot]) -> None:
        dots = {"ok": Status.OK, "denied": Status.ERROR, "refused": Status.ERROR, "failed": Status.ERROR,
                "expired": Status.WARN, "timeout": Status.WARN, "unknown": Status.WARN}
        lines = []
        for e in await self.audit.recent(200):
            who = e["user_name"] or "unknown"
            detail = f"\n-# {cards.truncate(e['detail'], 160)}" if e["detail"] else ""
            lines.append(f"{dots.get(e['outcome'], Status.OFF)} `{e['action']}` · {who} · {e['outcome']} · "
                         f"{cards.timestamp(e['at'], 'R')}{detail}")
        await Paginator.from_lines(lines or ["*Nothing yet.*"], per_page=10, title="Dashboard audit log",
                                   subtitle="Kept on the bot host, newest first").send(ctx, ephemeral=True)

    def link_summary(self) -> dict[str, Any]:
        client = self.client
        return {
            "paired": self.link is not None,
            "connected": bool(client and client.connected),
            "uptime": human_duration(time.time() - self.link.paired_at) if self.link else None,
        }
