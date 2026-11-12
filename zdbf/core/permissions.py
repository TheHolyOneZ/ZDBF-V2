# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from .bot import ZDBFBot

__all__ = [
    "MissingCommandRole",
    "OwnerOnly",
    "access_level",
    "admin_or_owner",
    "guild_owner_or_owner",
    "is_owner_only",
    "owner_only",
    "parent_checks",
    "role_permission_check",
]

_OWNER_ONLY_FLAG = "zdbf_owner_only"
_ACCESS_FLAG = "zdbf_access"


def _tagged_check(predicate: Any, level: str) -> Any:
    def decorator(func: Any) -> Any:
        if isinstance(func, commands.Command):
            func.extras[_ACCESS_FLAG] = level
        else:
            func.__zdbf_access__ = level
        return commands.check(predicate)(func)

    return decorator


class OwnerOnly(commands.CheckFailure):
    def __init__(self) -> None:
        super().__init__("This command is restricted to the bot owner.")


class MissingCommandRole(commands.CheckFailure):
    def __init__(self, command: str, role_ids: list[int]) -> None:
        self.command = command
        self.role_ids = role_ids
        super().__init__(f"You need one of the configured roles to use `{command}`.")


def owner_only():
    async def predicate(ctx: commands.Context[Any]) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True
        raise OwnerOnly()

    def decorator(func: Any) -> Any:
        if isinstance(func, commands.Command):
            func.extras[_OWNER_ONLY_FLAG] = True
        else:
            func.__zdbf_owner_only__ = True
        return commands.check(predicate)(func)

    return decorator


def is_owner_only(command: commands.Command[Any, ..., Any]) -> bool:
    cur: commands.Command[Any, ..., Any] | None = command
    while cur is not None:
        if cur.extras.get(_OWNER_ONLY_FLAG) or getattr(cur.callback, "__zdbf_owner_only__", False):
            return True
        cur = cur.parent  # type: ignore[assignment]
    return False


def access_level(command: commands.Command[Any, ..., Any]) -> str:
    if is_owner_only(command):
        return "Bot owner"
    cur: commands.Command[Any, ..., Any] | None = command
    while cur is not None:
        level = cur.extras.get(_ACCESS_FLAG) or getattr(cur.callback, "__zdbf_access__", None)
        if level:
            return str(level)
        cur = cur.parent  # type: ignore[assignment]
    return "Everyone"


def guild_owner_or_owner():
    async def predicate(ctx: commands.Context[Any]) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if ctx.guild.owner_id == ctx.author.id:
            return True
        raise commands.CheckFailure("Only the server owner can use this command.")

    return _tagged_check(predicate, "Server owner")


def admin_or_owner():
    async def predicate(ctx: commands.Context[Any]) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        assert isinstance(ctx.author, discord.Member)
        if ctx.author.guild_permissions.manage_guild:
            return True
        raise commands.MissingPermissions(["manage_guild"])

    return _tagged_check(predicate, "Manage Server permission")


async def parent_checks(ctx: commands.Context[Any]) -> bool:
    command = ctx.command
    parent = command.parent if command is not None else None
    while parent is not None:
        for predicate in parent.checks:
            if not await discord.utils.maybe_coroutine(predicate, ctx):
                raise commands.CheckFailure(f"You cannot use the `{parent.qualified_name}` commands.")
        parent = parent.parent
    return True


async def role_permission_check(ctx: commands.Context[ZDBFBot]) -> bool:
    command = ctx.command
    if command is None or ctx.guild is None or not isinstance(ctx.author, discord.Member):
        return True
    if ctx.author.id == ctx.guild.owner_id or ctx.author.guild_permissions.administrator:
        return True
    if await ctx.bot.is_owner(ctx.author):
        return True
    table = await ctx.bot.get_permission_table(ctx.guild.id)
    if not table:
        return True
    cur: commands.Command[Any, ..., Any] | None = command
    while cur is not None:
        roles = table.get(cur.qualified_name)
        if roles:
            if any(r.id in roles for r in ctx.author.roles):
                return True
            raise MissingCommandRole(cur.qualified_name, roles)
        cur = cur.parent  # type: ignore[assignment]
    return True
