# ZSync Marketplace client - Copyright (c) 2025-2026 TheHolyOneZ (TheZ). All rights reserved.
# Licensed under the ZSync Marketplace License (LICENSE-MARKETPLACE), NOT the Apache License.
# The names ZSync, ZDBF, Zoryx, TheHolyOneZ and TheZ must not be removed or altered.
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..core.database import utcnow_iso
from ..core.permissions import owner_only
from ..core.storage import global_file_handler
from ..ui import BaseView, Status, button, cards, confirm, row
from .client import Extension, KeyNotActivated, MarketplaceClient, MarketplaceError, safety_scan
from .deps import MISSING_RE, describe_command, install_packages, packages_for, required_packages
from .key import KEY_FILE, ensure_key
from .views import LicenseView, MarketplaceView

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot

log = logging.getLogger("zdbf.marketplace")

ACTIVATION_HELP = (
    "Your **ZSync ZDBF Key** is not activated yet (or was deactivated).\n\n"
    "**How to activate it**\n"
    "1. Show your key with `/marketplace key` (bot owner, sent privately).\n"
    "2. Fill in the form at https://zsync.eu/extension/activate.php\n"
    "3. Confirm the link we email you.\n"
    "4. You get a second email as soon as your key is activated.\n\n"
    "Questions? Join the ZSync Discord: https://discord.gg/GMqmnvdevD"
)
class InstallView(BaseView):
    def __init__(self, cog: Marketplace, ext: Extension, source: str, scan: dict[str, Any], author_id: int) -> None:
        super().__init__(author_id=author_id, timeout=900)
        self.cog = cog
        self.ext = ext
        self.source = source
        self.scan = scan
        self.stage = "confirm"
        self.result: str | None = None
        self.auto = cog.bot.config.settings.marketplace.auto_install_packages
        self.packages = required_packages(scan, own_module=ext.module_name)
        self.optional = packages_for(scan.get("optional_imports", []))

    @property
    def path(self) -> Path:
        return self.cog.bot.ext.directory / self.ext.filename

    def _package_lines(self) -> list[str]:
        if not self.packages and not self.optional:
            return []
        lines = []
        if self.packages:
            names = ", ".join(f"`{p}`" for p in self.packages)
            if self.auto:
                lines.append(f"{Status.WARN} **Needs packages that are not installed:** {names}\n"
                             f"-# **Install and load** runs `{describe_command(self.packages)}` in the bot's "
                             "environment first, then loads the extension.")
            else:
                lines.append(f"{Status.WARN} **Missing packages:** {names}\n"
                             "-# Install them with `/marketplace fixdeps` after installing.")
        if self.optional:
            lines.append("-# Optional packages it can use but does not need: "
                         + ", ".join(f"`{p}`" for p in self.optional))
        return lines

    def build(self) -> None:
        self.clear_items()
        ext = self.ext
        if self.stage == "confirm":
            flags = self.scan.get("flags", [])
            imports = ", ".join(f"`{m}`" for m in self.scan.get("imports", [])[:25]) or "-"
            body: list[Any] = [
                cards.kv({"File": f"`{self.path}`", "Size": f"{len(self.source):,} bytes · {self.scan.get('lines', 0)} lines",
                          "Entry point": f"{Status.OK} `setup()` found" if self.scan.get("has_setup")
                          else f"{Status.WARN} no `async def setup`"}),
                f"**Imports** {imports}",
                *self._package_lines(),
            ]
            if flags:
                body.append(f"{Status.WARN} **Review before loading:** " + ", ".join(flags)
                            + "\n-# Informational only - these are common in legitimate extensions too.")
            if self.path.exists():
                body.append(f"{Status.WARN} `{self.path.name}` already exists and will be **overwritten**.")
            if not self.scan.get("ok"):
                body.append(f"{Status.ERROR} {self.scan.get('error')}")
            box = cards.card(f"Install {ext.title} v{ext.version}?", *body, accent="warning")
            blocked = not self.scan.get("ok")
            with_deps = bool(self.packages) and self.auto
            box.add_item(row(
                button("Install and load", self._install_and_load, style=discord.ButtonStyle.success, disabled=blocked),
                button("Install file only" if with_deps else "Install only", self._install_only, disabled=blocked),
                button("Cancel", self._cancel)))
            self.add_item(box)
            return
        if self.stage == "working":
            self.add_item(cards.card(f"Installing {ext.title}", self.result or "Working...", accent="muted"))
            return
        if self.stage == "installed":
            loaded = self.cog.bot.ext.module_for(ext.module_name) in self.cog.bot.extensions
            box = cards.card(f"{ext.title} installed", self.result or "", accent="success")
            box.add_item(row(button("Reload now" if loaded else "Load now", self._load,
                                    style=discord.ButtonStyle.primary)))
            self.add_item(box)
            return
        self.add_item(cards.card(ext.title, self.result or "Done.",
                                 accent="success" if self.stage == "loaded" else "muted"))

    async def _working(self, interaction: discord.Interaction[Any], text: str) -> None:
        self.stage, self.result = "working", text
        await self.refresh(interaction)

    async def _owner(self, interaction: discord.Interaction[Any]) -> bool:
        if await self.cog.bot.is_owner(interaction.user):
            return True
        await interaction.response.send_message(
            view=cards.error("Owner only", "Only the bot owner can install extensions."), ephemeral=True)
        return False

    async def _install_only(self, interaction: discord.Interaction[Any]) -> None:
        await self._run(interaction, load=False)

    async def _install_and_load(self, interaction: discord.Interaction[Any]) -> None:
        await self._run(interaction, load=True)

    async def _run(self, interaction: discord.Interaction[Any], *, load: bool) -> None:
        if not await self._owner(interaction):
            return
        await interaction.response.defer()
        await self._working(interaction, "Saving the file...")
        if not await global_file_handler.atomic_write(self.path, self.source):
            self.stage, self.result = "failed", f"{Status.ERROR} Could not write `{self.path}`."
            await self.refresh(interaction)
            self.stop()
            return
        await self.cog.record_install(self.ext, self.source)
        notes = [f"{Status.OK} Saved to `{self.path}`."]
        notes += [f"{Status.WARN} {p}" for p in self.cog.bot.plugins.preflight(self.ext.module_name, self.path)]
        if load and self.packages and self.auto:
            await self._working(interaction, "\n".join(notes) + f"\n{Status.WARN} Installing "
                                + ", ".join(f"`{p}`" for p in self.packages) + "... this can take a few minutes.")
            pip = await install_packages(self.packages)
            if not pip.ok:
                notes.append(f"{Status.ERROR} Package install failed: {pip.error}")
                if pip.output:
                    notes.append(cards.codeblock("\n".join(pip.output)))
                notes.append("-# The extension was not loaded. Fix the packages, then use **Load now** "
                             "or `/marketplace fixdeps`.")
                self.stage, self.result = "installed", cards.truncate("\n".join(notes), 3500)
                await self.refresh(interaction)
                return
            notes.append(f"{Status.OK} Installed with {pip.tool}: " + ", ".join(f"`{p}`" for p in pip.packages))
            self.packages = required_packages(self.scan, own_module=self.ext.module_name)
        if not load:
            self.stage, self.result = "installed", "\n".join(notes)
            await self.refresh(interaction)
            return
        await self._working(interaction, "\n".join(notes) + f"\n{Status.WARN} Loading the extension...")
        await self._finish_load(interaction, notes)

    async def _finish_load(self, interaction: discord.Interaction[Any], notes: list[str]) -> None:
        res = await self.cog.bot.ext.reload(self.ext.module_name)
        if res.ok:
            notes.append(f"{Status.OK} {res.action.title()}ed in {res.elapsed_ms:.0f} ms.")
            self.stage, self.result = "loaded", "\n".join(notes)
            await self.refresh(interaction)
            self.stop()
            return
        notes.append(f"{Status.ERROR} {res.error}")
        missing = packages_for(MISSING_RE.findall(res.error or ""))
        notes.append(f"-# Still missing: {', '.join(f'`{p}`' for p in missing)}. Try `/marketplace fixdeps`."
                     if missing else "-# Check the error, then use **Load now** to try again.")
        self.stage, self.result = "installed", cards.truncate("\n".join(notes), 3500)
        await self.refresh(interaction)

    async def _load(self, interaction: discord.Interaction[Any]) -> None:
        if not await self._owner(interaction):
            return
        await interaction.response.defer()
        await self._working(interaction, f"{Status.WARN} Loading the extension...")
        await self._finish_load(interaction, [])

    async def _cancel(self, interaction: discord.Interaction[Any]) -> None:
        self.stage, self.result = "cancelled", "Installation cancelled."
        await self.refresh(interaction)
        self.stop()


class Marketplace(commands.Cog, name="Marketplace"):
    """Browse, install and update extensions from the ZSync Marketplace."""

    KV_LICENSE = "marketplace.license_accepted"
    KV_INSTALLED = "marketplace.installed"

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        s = bot.config.settings.marketplace
        self.client = MarketplaceClient(s.api_url, s.download_url, s.cache_minutes)
        self.accepted: set[int] = set()
        self.installed: dict[str, dict[str, Any]] = {}

    async def cog_load(self) -> None:
        self.accepted = {int(u) for u in await self.bot.db.kv_get(self.KV_LICENSE, [])}
        legacy = Path("data/marketplace/license_accepted.json")
        if legacy.exists():
            data = await global_file_handler.atomic_read_json(legacy) or {}
            self.accepted |= {int(u) for u in data.get("accepted_users", []) if str(u).isdigit()}
            await self.bot.db.kv_set(self.KV_LICENSE, sorted(self.accepted))
        self.installed = await self.bot.db.kv_get(self.KV_INSTALLED, {})
        _, origin = await ensure_key()
        if origin == "migrated":
            log.info("ZygnalID migrated to the ZSync ZDBF Key (%s)", KEY_FILE)

    async def cog_unload(self) -> None:
        await self.client.close()

    async def gate(self, ctx: commands.Context[ZDBFBot]) -> bool:
        if ctx.author.id in self.accepted:
            return True
        view = LicenseView(ctx.author.id)
        await view.send(ctx, ephemeral=True)
        await view.wait()
        if not view.accepted:
            return False
        self.accepted.add(ctx.author.id)
        await self.bot.db.kv_set(self.KV_LICENSE, sorted(self.accepted))
        return True

    async def record_install(self, ext: Extension, source: str) -> None:
        self.installed[ext.filename] = {"id": ext.id, "title": ext.title, "version": ext.version,
                                        "installed_at": utcnow_iso(),
                                        "sha256": hashlib.sha256(source.encode()).hexdigest()}
        await self.bot.db.kv_set(self.KV_INSTALLED, self.installed)

    async def _error(self, target: commands.Context[ZDBFBot] | discord.Interaction[Any], title: str, text: str) -> None:
        view = cards.error(title, text)
        if isinstance(target, discord.Interaction):
            if target.response.is_done():
                await target.followup.send(view=view, ephemeral=True)
            else:
                await target.response.send_message(view=view, ephemeral=True)
        else:
            await target.send(view=view, ephemeral=True)

    async def install_flow(self, interaction: discord.Interaction[Any], ext: Extension) -> None:
        if not await self.bot.is_owner(interaction.user):
            await self._error(interaction, "Owner only", "Only the bot owner can install extensions.")
            return
        if interaction.user.id not in self.accepted:
            await self._error(interaction, "License required", "Run `/marketplace` once and accept the license.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        key, _ = await ensure_key()
        try:
            source = await self.client.download(ext, key)
        except KeyNotActivated:
            await interaction.followup.send(view=cards.warning("Key not activated", ACTIVATION_HELP), ephemeral=True)
            return
        except MarketplaceError as exc:
            await interaction.followup.send(view=cards.error("Download failed", str(exc)), ephemeral=True)
            return
        view = InstallView(self, ext, source, safety_scan(source), interaction.user.id)
        await view.send(interaction, ephemeral=True)

    async def _find(self, ctx: commands.Context[ZDBFBot], ref: str) -> Extension | None:
        try:
            ext = await self.client.get(ref)
        except MarketplaceError as exc:
            await ctx.send(view=cards.error("Marketplace unavailable", str(exc)))
            return None
        if ext is None:
            await ctx.send(view=cards.error("Not found", f"No extension matches `{ref}`. Try `/marketplace search`."))
        return ext

    async def _ext_ac(self, interaction: discord.Interaction[Any], current: str) -> list[app_commands.Choice[str]]:
        try:
            items = await self.client.search(current) if current else await self.client.list()
        except MarketplaceError:
            return []
        return [app_commands.Choice(name=f"{e.title} v{e.version} · {e.creator}"[:100], value=str(e.id))
                for e in items[:25]]

    @commands.hybrid_group(name="marketplace", aliases=["mp", "mkt"], fallback="browse",
                           description="ZSync extension marketplace", invoke_without_command=True)
    async def marketplace(self, ctx: commands.Context[ZDBFBot]) -> None:
        if not await self.gate(ctx):
            return
        try:
            items = await self.client.list()
        except MarketplaceError as exc:
            await ctx.send(view=cards.error("Marketplace unavailable", str(exc)))
            return
        await MarketplaceView(self, items, ctx.author.id).send(ctx)

    @marketplace.command(name="search", description="Search extensions")
    async def mp_search(self, ctx: commands.Context[ZDBFBot], *, query: str) -> None:
        if not await self.gate(ctx):
            return
        try:
            items = await self.client.search(query)
        except MarketplaceError as exc:
            await ctx.send(view=cards.error("Marketplace unavailable", str(exc)))
            return
        await MarketplaceView(self, items, ctx.author.id, title="Search results", query=query).send(ctx)

    @marketplace.command(name="info", description="Details for one extension")
    @app_commands.autocomplete(extension=_ext_ac)
    async def mp_info(self, ctx: commands.Context[ZDBFBot], *, extension: str) -> None:
        if not await self.gate(ctx):
            return
        ext = await self._find(ctx, extension)
        if ext is None:
            return
        view = MarketplaceView(self, [ext], ctx.author.id)
        view.selected = ext
        await view.send(ctx)

    @marketplace.command(name="install", description="Download and install an extension (bot owner)")
    @app_commands.autocomplete(extension=_ext_ac)
    @owner_only()
    async def mp_install(self, ctx: commands.Context[ZDBFBot], *, extension: str) -> None:
        if not await self.gate(ctx):
            return
        ext = await self._find(ctx, extension)
        if ext is None:
            return
        if ctx.interaction is not None:
            await self.install_flow(ctx.interaction, ext)
            return
        view = MarketplaceView(self, [ext], ctx.author.id)
        view.selected = ext
        await view.send(ctx)

    @marketplace.command(name="uninstall", description="Unload and delete an installed extension (bot owner)")
    @owner_only()
    async def mp_uninstall(self, ctx: commands.Context[ZDBFBot], *, name: str) -> None:
        mgr = self.bot.ext
        module = mgr.module_for(name)
        path = mgr.path_for(module)
        if path is None or path.name == "__init__.py":
            await ctx.send(view=cards.error("Not found", f"No single-file extension `{name}` in `{mgr.directory}`."))
            return
        view = await confirm(ctx, f"Uninstall {path.stem}?", f"The extension is unloaded and `{path}` is deleted.",
                             confirm_label="Uninstall")
        if not view.value:
            return
        if module in self.bot.extensions:
            await mgr.unload(module)
        path.unlink(missing_ok=True)
        self.installed.pop(path.name, None)
        await self.bot.db.kv_set(self.KV_INSTALLED, self.installed)
        assert view.interaction is not None
        await view.interaction.followup.send(view=cards.success("Uninstalled", f"`{path.name}` removed."))

    @marketplace.command(name="updates", description="Check installed extensions for updates")
    async def mp_updates(self, ctx: commands.Context[ZDBFBot]) -> None:
        if not await self.gate(ctx):
            return
        try:
            items = {e.filename: e for e in await self.client.list(refresh=True)}
        except MarketplaceError as exc:
            await ctx.send(view=cards.error("Marketplace unavailable", str(exc)))
            return
        outdated = [(meta, items[f]) for f, meta in self.installed.items() if f in items
                    and items[f].version != meta.get("version")]
        lines = [f"{Status.WARN} **{e.title}** v{meta.get('version')} → **v{e.version}**" for meta, e in outdated]
        lines += [f"{Status.OK} {meta.get('title', f)} v{meta.get('version')}" for f, meta in self.installed.items()
                  if f not in {e.filename for _, e in outdated}]
        box = cards.card("Extension updates", "\n".join(lines) or "*No marketplace extensions installed yet.*", accent="warning" if outdated else "success",
                         foot=f"{len(outdated)} update(s) available")
        if outdated:
            view = MarketplaceView(self, [e for _, e in outdated], ctx.author.id, title="Updates available")
            view.filter = "all"
            await view.send(ctx)
            return
        await ctx.send(view=cards.static(box))

    @marketplace.command(name="refresh", description="Refresh the extension list cache (bot owner)")
    @owner_only()
    async def mp_refresh(self, ctx: commands.Context[ZDBFBot]) -> None:
        try:
            items = await self.client.list(refresh=True)
        except MarketplaceError as exc:
            await ctx.send(view=cards.error("Refresh failed", str(exc)))
            return
        await ctx.send(view=cards.success("Marketplace refreshed", f"{len(items)} extensions available."))

    @marketplace.command(name="key", aliases=["myid"], description="Show this installation's ZSync ZDBF Key (bot owner)")
    @owner_only()
    async def mp_key(self, ctx: commands.Context[ZDBFBot]) -> None:
        key, origin = await ensure_key()
        note = {"migrated": "\n-# Migrated from your old ZygnalID - activation carries over.",
                "generated": "\n-# Newly generated - it must be activated before downloads work."}.get(origin, "")
        view = cards.static(cards.card("Your ZSync ZDBF Key", f"```{key}```\nUse it when contacting ZSync support. "
                                       f"Never share it publicly.{note}", accent="gold",
                                       foot=f"Stored in {KEY_FILE}"))
        if ctx.interaction is not None:
            await ctx.send(view=view, ephemeral=True)
            return
        try:
            await ctx.author.send(view=view)
            await ctx.send(view=cards.success("Sent", "Check your DMs."), delete_after=10)
        except discord.Forbidden:
            await ctx.send(view=cards.error("DMs closed", "Use `/marketplace key` instead."), delete_after=10)

    @marketplace.command(name="fixdeps", description="Install missing Python packages for failed extensions (bot owner)")
    @commands.cooldown(1, 60, commands.BucketType.user)
    @owner_only()
    async def mp_fixdeps(self, ctx: commands.Context[ZDBFBot]) -> None:
        await ctx.defer()
        sources = list(self.bot.ext.failed.values())
        log_file = Path(self.bot.config.settings.logging.directory) / "zdbf.log"
        if log_file.exists():
            sources.append((await asyncio.to_thread(log_file.read_text, encoding="utf-8", errors="ignore"))[-500_000:])
        packages = packages_for({m for text in sources for m in MISSING_RE.findall(text)})
        if not packages:
            await ctx.send(view=cards.success("No missing packages", "No `ModuleNotFoundError` for an uninstalled "
                                                                    "package was found."))
            return
        view = await confirm(ctx, "Install packages?", "\n".join(f"• `{p}`" for p in packages)
                             + f"\n\nRuns `{describe_command(packages)}` in the bot's environment.",
                             confirm_label="Install", danger=False)
        if not view.value or view.interaction is None:
            return
        pip = await install_packages(packages)
        ok = pip.ok
        tail = pip.output or [pip.error or ""]
        retry = BaseView(author_id=ctx.author.id)
        box = cards.card("Packages installed" if ok else f"{pip.tool} reported an error",
                         cards.codeblock("\n".join(tail)), accent="success" if ok else "error")

        async def retry_failed(interaction: discord.Interaction[Any]) -> None:
            await interaction.response.defer()
            results = [await self.bot.ext.load(m) for m in list(self.bot.ext.failed)]
            text = "\n".join(f"{Status.OK if r.ok else Status.ERROR} {r.name}" + ("" if r.ok else f" - {r.error}")
                             for r in results) or "Nothing to retry."
            await interaction.followup.send(view=cards.info("Retry", cards.truncate(text, 3500)))

        if self.bot.ext.failed:
            box.add_item(row(button("Retry failed extensions", retry_failed)))
        retry.add_item(box)
        retry.message = await view.interaction.followup.send(view=retry, wait=True)


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(Marketplace(bot))
