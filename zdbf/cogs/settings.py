# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..core.permissions import admin_or_owner, guild_owner_or_owner, is_owner_only
from ..ui import BaseView, Paginator, SelectPager, cards, chunk_lines, nav_row
from .core import send_group_help

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot


class PermissionsView(BaseView):
    PER_PAGE = 12

    def __init__(self, bot: ZDBFBot, guild: discord.Guild, table: dict[str, list[int]], author_id: int) -> None:
        super().__init__(author_id=author_id)
        self.bot = bot
        self.guild = guild
        self.table = table
        self.page = 0
        self.remover = SelectPager([], self._remove, placeholder="Remove restrictions", max_values=25)

    async def _remove(self, interaction: discord.Interaction[Any], values: list[str]) -> None:
        for cmd in values:
            await self.bot.db.clear_command_roles(self.guild.id, cmd)
            self.table.pop(cmd, None)
        self.bot.invalidate_permissions(self.guild.id)
        await self.refresh(interaction)

    async def _goto(self, interaction: discord.Interaction[Any], index: int) -> None:
        self.page = index
        await self.refresh(interaction)

    def build(self) -> None:
        self.clear_items()
        items = sorted(self.table.items())
        pages = max(1, (len(items) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page = min(self.page, pages - 1)
        chunk = items[self.page * self.PER_PAGE:(self.page + 1) * self.PER_PAGE]
        body = "\n".join(f"`{cmd}`  {', '.join(f'<@&{r}>' for r in roles)}" for cmd, roles in chunk) or \
            "*No restrictions. Every command uses its default permissions.*"
        box = cards.card(
            "Command permissions",
            body,
            cards.sep(),
            "-# Restricting a group (for example `backup`) applies to all of its subcommands; a more specific "
            "entry (`backup create`) takes precedence. The server owner and administrators are never restricted.\n"
            "-# Add a rule with `/settings permissions add`.",
            subtitle=f"{len(items)} rule(s)",
            accent="primary",
            foot=f"Page {self.page + 1} of {pages}" if pages > 1 else None,
        )
        if pages > 1:
            box.add_item(nav_row(self.page, pages, self._goto))
        self.remover.set_options([discord.SelectOption(label=cmd[:100], value=cmd, description=f"{len(roles)} role(s)")
                                  for cmd, roles in items])
        for r in self.remover.rows(self):
            box.add_item(r)
        self.add_item(box)


class Settings(commands.Cog, name="Server Settings"):
    """Prefix, mention prefix and role restrictions for this server."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="settings", description="Server settings", invoke_without_command=True)
    @commands.guild_only()
    async def settings(self, ctx: commands.Context[ZDBFBot]) -> None:
        await self.settings_view.callback(self, ctx)  # type: ignore[arg-type]

    @settings.command(name="view", description="Show this server's settings")
    @commands.guild_only()
    async def settings_view(self, ctx: commands.Context[ZDBFBot]) -> None:
        assert ctx.guild is not None
        prefix, mention = await self.bot.guild_prefix(ctx.guild.id)
        default = self.bot.config.settings.bot.prefix
        table = await self.bot.get_permission_table(ctx.guild.id)
        stored = await self.bot.db.all_settings(ctx.guild.id)
        extra = {k: v for k, v in stored.items() if k not in ("prefix", "mention_prefix")}
        body: list[Any] = [
            cards.kv({
                "Prefix": f"`{prefix}`" + ("" if prefix != default else " *(default)*"),
                "Mention prefix": "enabled" if mention else "disabled",
                "Command restrictions": len(table),
                "Shard": ctx.guild.shard_id,
            }),
        ]
        hint = (f"-# Change with `{prefix}settings prefix`, `{prefix}settings mentionprefix` and "
                f"`{prefix}settings permissions list`.")
        stored_lines = [f"`{k}`  {cards.truncate(v, 120)}" for k, v in sorted(extra.items())]
        pages = [[*body, cards.sep(), f"**Stored settings** · {len(stored_lines)}\n{chunk}", cards.sep(), hint]
                 for chunk in chunk_lines(stored_lines, per_page=12)] if stored_lines else [[*body, cards.sep(), hint]]
        await Paginator(pages, title=ctx.guild.name, subtitle="Server settings",
                        thumbnail=ctx.guild.icon.url if ctx.guild.icon else None).send(ctx)

    @settings.command(name="prefix", description="Set (or reset) the command prefix for this server")
    @app_commands.describe(prefix="New prefix, or 'reset' for the default")
    @commands.guild_only()
    @admin_or_owner()
    async def settings_prefix(self, ctx: commands.Context[ZDBFBot], prefix: str) -> None:
        assert ctx.guild is not None
        if prefix.lower() in ("reset", "default"):
            await self.bot.db.set_guild_prefix(ctx.guild.id, None)
            new = self.bot.config.settings.bot.prefix
        else:
            if len(prefix) > 10 or any(c.isspace() for c in prefix):
                await ctx.send(view=cards.error("Invalid prefix", "Use up to 10 characters without spaces."))
                return
            await self.bot.db.set_guild_prefix(ctx.guild.id, prefix)
            new = prefix
        self.bot.prefix_cache.invalidate(ctx.guild.id)
        await ctx.send(view=cards.success("Prefix updated", f"Commands now use `{new}` - e.g. `{new}help`.\n"
                                                             "Slash commands always work."))

    @settings.command(name="mentionprefix", description="Allow or block @Bot as a command prefix")
    @commands.guild_only()
    @admin_or_owner()
    async def settings_mention(self, ctx: commands.Context[ZDBFBot], enabled: bool) -> None:
        assert ctx.guild is not None
        await self.bot.db.set_guild_mention_prefix_enabled(ctx.guild.id, enabled)
        self.bot.prefix_cache.invalidate(ctx.guild.id)
        await ctx.send(view=cards.success("Mention prefix " + ("enabled" if enabled else "disabled"),
                                          f"`@{self.bot.user.name if self.bot.user else 'Bot'} help` "
                                          + ("now works." if enabled else "is ignored now.")))

    @settings.group(name="permissions", description="Restrict commands to roles", invoke_without_command=True)
    @commands.guild_only()
    async def permissions(self, ctx: commands.Context[ZDBFBot]) -> None:
        await send_group_help(ctx)

    async def _command_ac(self, interaction: discord.Interaction[Any], current: str) -> list[app_commands.Choice[str]]:
        names = sorted({c.qualified_name for c in self.bot.walk_commands()
                        if not c.hidden and not is_owner_only(c) and c.cog_name != "Compatibility"})
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n][:25]

    @permissions.command(name="list", description="Show command restrictions")
    @commands.guild_only()
    @guild_owner_or_owner()
    async def permissions_list(self, ctx: commands.Context[ZDBFBot]) -> None:
        assert ctx.guild is not None
        table = await self.bot.db.list_command_permissions(ctx.guild.id)
        await PermissionsView(self.bot, ctx.guild, table, ctx.author.id).send(ctx)

    @permissions.command(name="add", description="Require a role for a command")
    @app_commands.autocomplete(command=_command_ac)
    @commands.guild_only()
    @guild_owner_or_owner()
    async def permissions_add(self, ctx: commands.Context[ZDBFBot], role: discord.Role, *, command: str) -> None:
        assert ctx.guild is not None
        cmd = self.bot.get_command(command)
        if cmd is None or is_owner_only(cmd):
            await ctx.send(view=cards.error("Unknown command", f"`{command}` is not a server command."))
            return
        await self.bot.db.add_command_role(ctx.guild.id, cmd.qualified_name, role.id)
        self.bot.invalidate_permissions(ctx.guild.id)
        roles = await self.bot.db.get_command_roles(ctx.guild.id, cmd.qualified_name)
        await ctx.send(view=cards.success("Restriction added", f"`{cmd.qualified_name}` now requires one of: "
                                          + ", ".join(f"<@&{r}>" for r in roles)))

    @permissions.command(name="remove", description="Remove a role from a command's restriction")
    @app_commands.autocomplete(command=_command_ac)
    @commands.guild_only()
    @guild_owner_or_owner()
    async def permissions_remove(self, ctx: commands.Context[ZDBFBot], role: discord.Role, *, command: str) -> None:
        assert ctx.guild is not None
        cmd = self.bot.get_command(command)
        name = cmd.qualified_name if cmd else command
        removed = await self.bot.db.remove_command_role(ctx.guild.id, name, role.id)
        self.bot.invalidate_permissions(ctx.guild.id)
        await ctx.send(view=(cards.success("Restriction updated", f"{role.mention} removed from `{name}`.") if removed
                             else cards.warning("Nothing changed", f"{role.mention} was not required for `{name}`.")))

    @permissions.command(name="clear", description="Remove every restriction from a command")
    @app_commands.autocomplete(command=_command_ac)
    @commands.guild_only()
    @guild_owner_or_owner()
    async def permissions_clear(self, ctx: commands.Context[ZDBFBot], *, command: str) -> None:
        assert ctx.guild is not None
        cmd = self.bot.get_command(command)
        name = cmd.qualified_name if cmd else command
        n = await self.bot.db.clear_command_roles(ctx.guild.id, name)
        self.bot.invalidate_permissions(ctx.guild.id)
        await ctx.send(view=cards.success("Restrictions cleared", f"Removed {n} role(s) from `{name}`."))


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(Settings(bot))
