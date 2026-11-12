# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import contextlib
import logging
import secrets
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..ui import cards
from .permissions import MissingCommandRole, OwnerOnly

if TYPE_CHECKING:
    from .bot import ZDBFBot

log = logging.getLogger("zdbf.errors")

__all__ = ["describe_error", "handle_app_command_error", "handle_command_error"]


def _fmt_perms(perms: list[str]) -> str:
    return ", ".join(f"`{p.replace('_', ' ').title()}`" for p in perms)


def _unwrap(error: BaseException) -> BaseException:
    while True:
        if isinstance(error, (commands.HybridCommandError, commands.CommandInvokeError)) and error.original:
            error = error.original
        elif isinstance(error, app_commands.CommandInvokeError) and error.original:
            error = error.original
        else:
            return error


def describe_error(error: BaseException, *, usage: str | None = None) -> tuple[str, str, str, bool]:
    error = _unwrap(error)
    match error:
        case OwnerOnly() | commands.NotOwner():
            return "error", "Owner only", "This command is restricted to the bot owner.", False
        case MissingCommandRole():
            roles = ", ".join(f"<@&{r}>" for r in error.role_ids[:5])
            return "error", "Missing role", f"You need one of these roles: {roles}", False
        case commands.MissingPermissions() | app_commands.MissingPermissions():
            return "error", "Missing permissions", f"You need {_fmt_perms(error.missing_permissions)}.", False
        case commands.BotMissingPermissions() | app_commands.BotMissingPermissions():
            return "error", "I'm missing permissions", f"I need {_fmt_perms(error.missing_permissions)}.", False
        case commands.MissingRole() | commands.MissingAnyRole():
            return "error", "Missing role", str(error), False
        case commands.NoPrivateMessage() | app_commands.NoPrivateMessage():
            return "warning", "Server only", "This command can only be used inside a server.", False
        case commands.PrivateMessageOnly():
            return "warning", "DM only", "This command only works in direct messages.", False
        case commands.CommandOnCooldown() | app_commands.CommandOnCooldown():
            return "warning", "Slow down", f"Try again in **{error.retry_after:.1f}s**.", False
        case commands.MaxConcurrencyReached():
            return "warning", "Busy", "This command is already running - please wait for it to finish.", False
        case commands.DisabledCommand():
            return "warning", "Disabled", "This command is currently disabled.", False
        case commands.MissingRequiredArgument():
            hint = f"\nUsage: `{usage}`" if usage else ""
            return "warning", "Missing argument", f"`{error.param.name}` is required.{hint}", False
        case commands.TooManyArguments():
            hint = f"\nUsage: `{usage}`" if usage else ""
            return "warning", "Too many arguments", f"Check the command usage.{hint}", False
        case commands.BadLiteralArgument():
            options = ", ".join(f"`{x}`" for x in error.literals)
            return "warning", "Invalid choice", f"`{error.param.name}` must be one of {options}.", False
        case commands.BadArgument() | commands.BadUnionArgument() | app_commands.TransformerError():
            return "warning", "Invalid argument", str(error), False
        case commands.UserInputError():
            return "warning", "Invalid input", str(error), False
        case commands.CheckFailure() | app_commands.CheckFailure():
            msg = str(error) or "You can't use this command here."
            if msg.startswith("The check functions for"):
                msg = "You can't use this command here."
            return "error", "Not allowed", msg, False
        case discord.Forbidden():
            return "error", "Forbidden", "Discord refused that action - check my role position and permissions.", False
        case discord.NotFound():
            return "warning", "Not found", "That message, channel or member no longer exists.", False
        case _:
            return "error", "Unexpected error", f"{type(error).__name__}: {cards.truncate(error, 300)}", True


async def handle_command_error(bot: ZDBFBot, ctx: commands.Context[Any], error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        return
    if ctx.command is not None and ctx.command.has_error_handler():
        return
    if ctx.cog is not None and ctx.cog.has_error_handler():
        return

    usage = f"{ctx.clean_prefix}{ctx.command.qualified_name} {ctx.command.signature}".strip() if ctx.command else None
    level, title, message, unexpected = describe_error(error, usage=usage)
    command_name = ctx.command.qualified_name if ctx.command else "unknown"
    if unexpected:
        bot.metrics.record_error(command_name, f"{type(_unwrap(error)).__name__}: {_unwrap(error)}",
                                 ctx.author.id, ctx.guild.id if ctx.guild else None)
    else:
        bot.metrics.record_rejection(type(_unwrap(error)).__name__)

    if unexpected:
        ref = secrets.token_hex(3)
        log.error("unhandled error in %s [ref %s]", command_name, ref, exc_info=_unwrap(error))
        message = f"{message}\n-# Reference `{ref}` - give this to the bot owner."
        await bot.alerts.send("errors", f"`{command_name}` failed [ref `{ref}`]: {cards.truncate(_unwrap(error), 500)}",
                              "error")
    else:
        log.debug("command %s rejected: %s", command_name, error)

    view = cards.static(cards.card(title, message, emoji=None, accent=level, foot=f"Command: {command_name}"))
    with contextlib.suppress(discord.HTTPException):
        if ctx.interaction is not None:
            if ctx.interaction.response.is_done():
                await ctx.interaction.followup.send(view=view, ephemeral=True)
            else:
                await ctx.interaction.response.send_message(view=view, ephemeral=True)
        else:
            await ctx.send(view=view, delete_after=15 if not unexpected else 30,
                           allowed_mentions=discord.AllowedMentions.none())


async def handle_app_command_error(
    bot: ZDBFBot, interaction: discord.Interaction[Any], error: app_commands.AppCommandError
) -> None:
    level, title, message, unexpected = describe_error(error)
    command_name = interaction.command.qualified_name if interaction.command else "unknown"
    if unexpected:
        bot.metrics.record_error(command_name, f"{type(_unwrap(error)).__name__}: {_unwrap(error)}",
                                 interaction.user.id, interaction.guild_id)
    else:
        bot.metrics.record_rejection(type(_unwrap(error)).__name__)
    if unexpected:
        ref = secrets.token_hex(3)
        log.error("unhandled app command error in %s [ref %s]", command_name, ref, exc_info=_unwrap(error))
        message = f"{message}\n-# Reference `{ref}`"
    view = cards.static(cards.card(title, message, accent=level, foot=f"Command: /{command_name}"))
    with contextlib.suppress(discord.HTTPException):
        if interaction.response.is_done():
            await interaction.followup.send(view=view, ephemeral=True)
        else:
            await interaction.response.send_message(view=view, ephemeral=True)
