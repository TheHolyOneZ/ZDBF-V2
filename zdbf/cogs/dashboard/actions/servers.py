# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from typing import Any

import discord

from ....core.permissions import is_owner_only
from . import ActionContext, ActionError, action
from .chat import discord_errors

KINDS = {
    discord.ChannelType.text: "text", discord.ChannelType.news: "news", discord.ChannelType.voice: "voice",
    discord.ChannelType.stage_voice: "stage", discord.ChannelType.forum: "forum",
    discord.ChannelType.category: "category", discord.ChannelType.media: "forum",
}


def guild_of(ctx: ActionContext) -> discord.Guild:
    guild = ctx.bot.get_guild(ctx.integer("guild_id", minimum=1))
    if guild is None:
        raise ActionError("The bot is not in that server any more.")
    return guild


def resources(guild: discord.Guild) -> dict[str, Any]:
    me = guild.me
    channels = []
    for channel in sorted(guild.channels, key=lambda c: (c.position, c.id)):
        kind = KINDS.get(channel.type)
        if kind is None:
            continue
        perms = channel.permissions_for(me)
        channels.append({"id": str(channel.id), "name": channel.name, "kind": kind,
                         "category": channel.category.name if channel.category else None,
                         "send": bool(perms.view_channel and perms.send_messages)})
    roles = [{"id": str(r.id), "name": r.name, "color": f"#{r.colour.value:06x}" if r.colour.value else None,
              "managed": r.managed, "assignable": r.is_assignable()}
             for r in sorted(guild.roles, key=lambda r: -r.position) if not r.is_default()]
    return {"channels": channels[:500], "roles": roles[:250]}


def server_commands(bot: Any) -> list[str]:
    return sorted({c.qualified_name for c in bot.walk_commands()
                   if not c.hidden and not is_owner_only(c) and c.cog_name != "Compatibility"})


@action("servers.list", "view", timeout=20)
async def listing(ctx: ActionContext) -> dict[str, Any]:
    out = []
    for guild in sorted(ctx.bot.guilds, key=lambda g: g.name.lower())[:500]:
        out.append({
            "id": str(guild.id), "name": guild.name, "icon": guild.icon.replace(size=64).url if guild.icon else None,
            "members": guild.member_count or 0, "owner_id": str(guild.owner_id) if guild.owner_id else None,
            "joined_at": guild.me.joined_at.timestamp() if guild.me and guild.me.joined_at else None,
            "shard": guild.shard_id, "channels": len(guild.channels), "roles": len(guild.roles),
            "boosts": guild.premium_subscription_count or 0,
        })
    return {"servers": out}


@action("servers.detail", "view", timeout=30)
async def detail(ctx: ActionContext) -> dict[str, Any]:
    guild = guild_of(ctx)
    bot = ctx.bot
    prefix, mention = await bot.guild_prefix(guild.id)
    stored = await bot.db.all_settings(guild.id)
    table = await bot.db.list_command_permissions(guild.id)
    owner = guild.owner
    me = guild.me
    perms = me.guild_permissions if me else discord.Permissions.none()
    return {
        "id": str(guild.id), "name": guild.name, "icon": guild.icon.replace(size=128).url if guild.icon else None,
        "description": guild.description, "members": guild.member_count or 0,
        "owner": {"id": str(guild.owner_id), "name": owner.display_name if owner else None},
        "created_at": guild.created_at.timestamp(), "shard": guild.shard_id,
        "joined_at": me.joined_at.timestamp() if me and me.joined_at else None,
        "prefix": prefix, "default_prefix": bot.config.settings.bot.prefix, "custom_prefix": "prefix" in stored,
        "mention_prefix": mention,
        "settings": {k: v for k, v in stored.items() if k not in ("prefix", "mention_prefix")},
        "restrictions": {name: [str(r) for r in roles] for name, roles in sorted(table.items())},
        "commands": server_commands(bot),
        "bot_permissions": {"administrator": perms.administrator, "manage_guild": perms.manage_guild,
                            "manage_roles": perms.manage_roles, "manage_channels": perms.manage_channels},
        **resources(guild),
    }


@action("servers.resources", "view", timeout=20)
async def guild_resources(ctx: ActionContext) -> dict[str, Any]:
    return resources(guild_of(ctx))


@action("servers.prefix", "settings", timeout=20,
        summary=lambda a: f"set the prefix of server {a.get('guild_id')} to {a.get('prefix') or 'the default'}")
async def set_prefix(ctx: ActionContext) -> dict[str, Any]:
    guild = guild_of(ctx)
    bot = ctx.bot
    prefix = ctx.text("prefix", default="", max_length=20).strip()
    if prefix and (len(prefix) > 10 or any(c.isspace() for c in prefix)):
        raise ActionError("Use up to 10 characters without spaces.")
    await bot.db.set_guild_prefix(guild.id, prefix or None)
    if "mention_prefix" in ctx.args:
        await bot.db.set_guild_mention_prefix_enabled(guild.id, ctx.flag("mention_prefix"))
    bot.prefix_cache.invalidate(guild.id)
    new, mention = await bot.guild_prefix(guild.id)
    return {"prefix": new, "mention_prefix": mention}


@action("servers.restrict", "settings", timeout=20,
        summary=lambda a: f"{'remove' if a.get('remove') else 'add'} a role restriction on {a.get('command')}")
async def restrict(ctx: ActionContext) -> dict[str, Any]:
    guild = guild_of(ctx)
    bot = ctx.bot
    name = ctx.text("command", max_length=100).strip()
    command = bot.get_command(name)
    if ctx.flag("clear"):
        await bot.db.clear_command_roles(guild.id, command.qualified_name if command else name)
    else:
        if command is None or is_owner_only(command):
            raise ActionError(f"{name} is not a server command.")
        role = guild.get_role(ctx.integer("role_id", minimum=1))
        if role is None:
            raise ActionError("That role does not exist.")
        if ctx.flag("remove"):
            await bot.db.remove_command_role(guild.id, command.qualified_name, role.id)
        else:
            await bot.db.add_command_role(guild.id, command.qualified_name, role.id)
        name = command.qualified_name
    bot.invalidate_permissions(guild.id)
    return {"command": name, "roles": [str(r) for r in await bot.db.get_command_roles(guild.id, name)]}


@action("servers.leave", "guilds.leave", timeout=30, summary=lambda a: f"leave server {a.get('guild_id')}")
@discord_errors
async def leave(ctx: ActionContext) -> dict[str, Any]:
    guild = guild_of(ctx)
    if ctx.text("confirm", max_length=100) != guild.name:
        raise ActionError("Type the server name exactly to confirm.")
    await guild.leave()
    return {"left": str(guild.id)}
