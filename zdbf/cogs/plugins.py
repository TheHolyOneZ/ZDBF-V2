# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..core.permissions import owner_only
from ..core.plugins import PluginMetadata
from ..ui import Glyph, ListDetailView, Paginator, Status, cards

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot


def plugin_card(bot: ZDBFBot, meta: PluginMetadata) -> discord.ui.Container[Any]:
    missing = bot.plugins.check_dependencies(meta)
    conflicts = bot.plugins.detect_conflicts(meta)
    deps = "\n".join(
        f"{Status.ERROR if any(m.startswith(d) for m in missing) else Status.OK} `{d}` {spec}".rstrip()
        for d, spec in meta.dependencies.items()
    ) or "*none*"
    names = sorted(meta.commands)
    cmds = ", ".join(f"`{c}`" for c in names[:40]) or "*none*"
    if len(names) > 40:
        cmds += f" and {len(names) - 40} more - see `/plugins commands {meta.name}`"
    return cards.card(
        meta.name,
        meta.description,
        cards.sep(),
        cards.kv({"Version": meta.version, "Author": meta.author, "Load time": f"{meta.load_time_ms:.0f} ms",
                  "Cogs": ", ".join(sorted(meta.cogs)) or "-", "File": f"`{meta.file_path or '-'}`"}),
        cards.sep(),
        f"**Dependencies**\n{deps}",
        f"**Conflicts with**\n{', '.join(f'`{c}`' for c in sorted(meta.conflicts_with)) or '*none*'}"
        + (f"\n{Status.ERROR} active conflicts: {', '.join(conflicts)}" if conflicts else ""),
        f"**Commands**\n{cmds}",
        (f"**Hooks** provides {', '.join(meta.provides_hooks) or '-'} · listens {', '.join(meta.listens_to_hooks) or '-'}"
         if meta.provides_hooks or meta.listens_to_hooks else None),
        ("**Scan errors**\n" + "\n".join(meta.scan_errors)) if meta.scan_errors else None,
        accent="error" if missing or conflicts else "primary",
    )


class PluginBrowser(ListDetailView[PluginMetadata]):
    title = "Plugin registry"
    placeholder = "Inspect a plugin"
    empty_text = "*No extensions loaded.*"
    per_page = 8

    def __init__(self, bot: ZDBFBot, author_id: int) -> None:
        super().__init__(sorted(bot.plugins.all().values(), key=lambda m: m.name.lower()), author_id=author_id)
        self.bot = bot

    def _bad(self, meta: PluginMetadata) -> bool:
        return bool(self.bot.plugins.check_dependencies(meta) or self.bot.plugins.detect_conflicts(meta))

    def item_key(self, item: PluginMetadata) -> str:
        return item.name

    def item_line(self, item: PluginMetadata) -> str:
        return (f"{Status.WARN if self._bad(item) else Status.OK} **{item.name}**  v{item.version} · {item.author}"
                f"\n-# {cards.truncate(item.description, 110)}")

    def item_option(self, item: PluginMetadata) -> discord.SelectOption:
        return discord.SelectOption(label=item.name[:100], value=item.name,
                                    description=f"v{item.version} · {item.author}"[:100])

    def subtitle(self) -> str:
        reg = self.bot.plugins
        return (f"{len(self.items)} plugins · dependency enforcement {'on' if reg.enforce_dependencies else 'off'} · "
                f"conflict enforcement {'on' if reg.enforce_conflicts else 'off'}")

    def detail(self, item: PluginMetadata) -> discord.ui.Container[Any]:
        return plugin_card(self.bot, item)


class Plugins(commands.Cog, name="Plugins"):
    """Extension metadata, dependency and conflict management."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot

    async def _plugin_ac(self, interaction: discord.Interaction[Any], current: str) -> list[app_commands.Choice[str]]:
        return [app_commands.Choice(name=n, value=n) for n in sorted(self.bot.plugins.all())
                if current.lower() in n.lower()][:25]

    @commands.hybrid_group(name="plugins", description="Plugin registry", invoke_without_command=True)
    async def plugins(self, ctx: commands.Context[ZDBFBot]) -> None:
        await self.plugin_list.callback(self, ctx)  # type: ignore[arg-type]

    @plugins.command(name="list", description="Browse registered plugins")
    async def plugin_list(self, ctx: commands.Context[ZDBFBot]) -> None:
        await PluginBrowser(self.bot, ctx.author.id).send(ctx)

    @plugins.command(name="info", description="Details for one plugin")
    @app_commands.autocomplete(name=_plugin_ac)
    async def plugin_info(self, ctx: commands.Context[ZDBFBot], *, name: str) -> None:
        meta = self.bot.plugins.get(name.removesuffix(".py"))
        if meta is None:
            await ctx.send(view=cards.error("Unknown plugin", f"`{name}` is not registered (is it loaded?)."))
            return
        await ctx.send(view=cards.static(plugin_card(self.bot, meta)))

    @plugins.command(name="commands", description="Every command a plugin provides")
    @app_commands.autocomplete(name=_plugin_ac)
    async def plugin_commands(self, ctx: commands.Context[ZDBFBot], *, name: str) -> None:
        meta = self.bot.plugins.get(name.removesuffix(".py"))
        if meta is None:
            await ctx.send(view=cards.error("Unknown plugin", f"`{name}` is not registered."))
            return
        await Paginator.from_lines([f"`{c}`" for c in sorted(meta.commands)] or ["*No commands.*"], per_page=20,
                                   title=f"{meta.name} commands", subtitle=f"{len(meta.commands)} commands").send(ctx)

    @plugins.command(name="validate", description="Check a plugin's dependencies and conflicts")
    @app_commands.autocomplete(name=_plugin_ac)
    @owner_only()
    async def plugin_validate(self, ctx: commands.Context[ZDBFBot], *, name: str) -> None:
        reg = self.bot.plugins
        meta = reg.get(name)
        if meta is None:
            path = self.bot.ext.path_for(self.bot.ext.module_for(name))
            if path is None:
                await ctx.send(view=cards.error("Unknown plugin", f"`{name}` is neither loaded nor in extensions/."))
                return
            problems = reg.preflight(name, path)
            title = f"Pre-load check: {name}"
        else:
            problems = reg.check_dependencies(meta) + [f"conflicts with {c}" for c in reg.detect_conflicts(meta)]
            if cycle := reg.find_cycle(meta.name):
                problems.append("circular dependency: " + " -> ".join(cycle))
            title = f"Validation: {name}"
        await ctx.send(view=(cards.success(title, "All dependencies satisfied, no conflicts.") if not problems
                             else cards.error(title, "\n".join(f"• {p}" for p in problems))))

    @plugins.command(name="enforce", description="Toggle dependency / conflict enforcement")
    @owner_only()
    async def plugin_enforce(self, ctx: commands.Context[ZDBFBot], dependencies: bool | None = None,
                             conflicts: bool | None = None) -> None:
        reg = self.bot.plugins
        if dependencies is not None:
            reg.enforce_dependencies = dependencies
        if conflicts is not None:
            reg.enforce_conflicts = conflicts
        await reg.save_settings()
        await ctx.send(view=cards.success("Enforcement", cards.kv({
            "Dependencies": "enforced" if reg.enforce_dependencies else "warn only",
            "Conflicts": "enforced" if reg.enforce_conflicts else "warn only"})))

    @plugins.command(name="alerts", description="Set the channel for plugin alerts")
    @owner_only()
    async def plugin_alerts(self, ctx: commands.Context[ZDBFBot], channel: discord.TextChannel | None = None) -> None:
        await self.bot.alerts.set_channel("plugins", channel.id if channel else None)
        await ctx.send(view=cards.success("Plugin alerts", f"→ {channel.mention if channel else '*cleared*'}"))

    @plugins.command(name="dependencies", description="Dependency tree of all plugins")
    async def plugin_tree(self, ctx: commands.Context[ZDBFBot]) -> None:
        plugins = self.bot.plugins.all()
        lines = []
        for name, meta in sorted(plugins.items()):
            lines.append(f"**{name}** v{meta.version}")
            for dep, spec in meta.dependencies.items():
                found = plugins.get(dep)
                icon = Status.OK if found else Status.ERROR
                lines.append(f"-# {Glyph.ARROW} {icon} {dep} {spec}".rstrip() + (f" (have {found.version})" if found else " (missing)"))
        await Paginator.from_lines(lines or ["*No plugins.*"], per_page=25, title="Dependency tree").send(ctx)


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(Plugins(bot))
