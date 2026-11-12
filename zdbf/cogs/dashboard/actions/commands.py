# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import copy
import inspect
import logging
import shlex
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.view import StringView

from ....core.bot import ACTING_AS_OWNER
from ....core.permissions import access_level
from ....core.slash_guard import run_app_command
from ...help import _OPTION_TYPES, HIDDEN_COGS, make_entry, options_of
from ..messages import channel_brief, serialize_message
from . import ActionContext, ActionError, action
from .chat import build_tree, discord_errors, resolve_channel

log = logging.getLogger("zdbf.dashboard.commands")

WAIT_SECONDS = 25.0
MAX_INVOCATION = 1900
MAX_RESULTS = 8
HARMLESS_CHECKS = frozenset({"guild_only", "dm_only", "is_nsfw", "bot_has_permissions", "bot_has_guild_permissions",
                             "bot_has_role", "bot_has_any_role"})


class CapturingContext(commands.Context[Any]):
    def __init__(self, **attrs: Any) -> None:
        super().__init__(**attrs)
        self.captured: list[discord.Message] = []

    async def send(self, *args: Any, **kwargs: Any) -> discord.Message:
        message = await super().send(*args, **kwargs)
        if message is not None:
            self.captured.append(message)
        return message


def _check_names(command: Any) -> list[str]:
    return [str(getattr(check, "__qualname__", "")).split(".")[0] for check in getattr(command, "checks", ())]


def restricted(command: commands.Command[Any, ..., Any]) -> bool:
    if access_level(command) != "Everyone":
        return True
    cur: commands.Command[Any, ..., Any] | None = command
    while cur is not None:
        if any(name not in HARMLESS_CHECKS for name in _check_names(cur)):
            return True
        cur = cur.parent  # type: ignore[assignment]
    cog = command.cog
    return cog is not None and type(cog).cog_check is not commands.Cog.cog_check


def app_restricted(command: app_commands.Command[Any, ..., Any]) -> bool:
    root = command.root_parent or command
    if command.default_permissions is not None or root.default_permissions is not None:
        return True
    return bool(command.checks) or bool(getattr(root, "checks", ()))


def ordinary_member(member: Any) -> Any:
    if not isinstance(member, discord.Member):
        return member
    plain = copy.copy(member)
    plain._roles = discord.utils.SnowflakeList(())
    return plain


def _app_only(bot: Any) -> list[app_commands.Command[Any, ..., Any]]:
    return [c for c in bot.tree.walk_commands()
            if isinstance(c, app_commands.Command) and not hasattr(c, "wrapped")]


def describe_commands(bot: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for command in bot.walk_commands():
        if command.hidden or command.cog_name in HIDDEN_COGS:
            continue
        if isinstance(command, commands.Group) and not getattr(command, "fallback", None):
            continue
        entry = make_entry(bot, command)
        params = []
        for (name, param), option in zip(command.clean_params.items(), options_of(command), strict=False):
            params.append({
                "name": name, "label": option.name, "kind": option.kind, "required": option.required,
                "default": option.default, "description": option.description, "choices": list(option.choices),
                "rest": param.kind in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.VAR_POSITIONAL),
            })
        out.append({
            "name": entry.prefix_name, "slash": entry.slash_name if entry.slash else None, "form": "prefix",
            "category": command.cog_name or "Other", "description": entry.description, "access": entry.access,
            "owner": restricted(command), "aliases": list(entry.aliases), "params": params,
        })
    for app in _app_only(bot):
        params = [
            {"name": p.name, "label": p.display_name, "kind": "choice" if p.choices else _OPTION_TYPES.get(p.type, p.type.name),
             "required": p.required, "default": None, "description": p.description if p.description not in ("…", "...") else "",
             "choices": [str(c.name) for c in p.choices], "rest": False}
            for p in app.parameters
        ]
        binding = getattr(app, "binding", None)
        category = getattr(binding, "qualified_name", None) or "Slash commands"
        out.append({
            "name": app.qualified_name, "slash": app.qualified_name, "form": "slash", "category": str(category),
            "description": app.description or "No description.", "access": "Restricted" if app_restricted(app) else "Everyone",
            "owner": app_restricted(app), "aliases": [], "params": params,
        })
    out.sort(key=lambda c: (c["category"].lower(), c["name"]))
    return out


def _quote(value: str) -> str:
    if value and not any(ch.isspace() or ch in "\"'“”" for ch in value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def clean_values(raw: Any) -> dict[str, str]:
    if raw is None or raw == []:
        return {}
    if not isinstance(raw, dict):
        raise ActionError("The command options could not be read.")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, bool):
            out[str(key)] = "true" if value else "false"
        elif isinstance(value, str | int | float) and str(value).strip() != "":
            out[str(key)] = str(value).strip()
    return out


def build_invocation(prefix: str, command: commands.Command[Any, ..., Any], values: dict[str, str]) -> str:
    parts = [f"{prefix}{command.qualified_name}"]
    gap: str | None = None
    known = set(command.clean_params)
    unknown = sorted(set(values) - known)
    if unknown:
        raise ActionError(f"`{command.qualified_name}` has no option named `{unknown[0]}`.")
    for name, param in command.clean_params.items():
        label = param.displayed_name or name
        raw = values.get(name)
        if raw is None:
            if param.required:
                raise ActionError(f"Fill in `{label}`.")
            gap = gap or label
            continue
        if gap is not None:
            raise ActionError(f"Fill in `{gap}` as well, or leave `{label}` empty. Options cannot be skipped here.")
        rest = param.kind in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.VAR_POSITIONAL)
        parts.append(raw if rest else _quote(raw))
    text = " ".join(parts)
    if len(text) > MAX_INVOCATION:
        raise ActionError("The command with its options is too long.")
    return text


def build_app_arguments(command: app_commands.Command[Any, ..., Any], values: dict[str, str]) -> str:
    tokens = command.qualified_name.split(" ")[1:]
    known = {p.name for p in command.parameters}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ActionError(f"`/{command.qualified_name}` has no option named `{unknown[0]}`.")
    gap: str | None = None
    for param in command.parameters:
        raw = values.get(param.name)
        if raw is None:
            if param.required:
                raise ActionError(f"Fill in `{param.display_name}`.")
            gap = gap or param.display_name
            continue
        if gap is not None:
            raise ActionError(f"Fill in `{gap}` as well, or leave `{param.display_name}` empty. Options cannot be skipped here.")
        tokens.append(shlex.quote(raw))
    return " ".join(tokens)


def make_context(bot: Any, message: Any, prefix: str) -> CapturingContext:
    view = StringView(message.content)
    ctx = CapturingContext(prefix=prefix, view=view, bot=bot, message=message)
    if view.skip_string(prefix):
        view.skip_ws()
        invoker = view.get_word()
        ctx.invoked_with = invoker
        ctx.command = bot.all_commands.get(invoker)
    return ctx


def _find_app(bot: Any, name: str) -> app_commands.Command[Any, ..., Any] | None:
    for command in _app_only(bot):
        if command.qualified_name == name:
            return command
    return None


def _consume(task: asyncio.Task[Any]) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("a dashboard command run failed", exc_info=task.exception())


async def _run(ctx: ActionContext, *, as_owner: bool) -> dict[str, Any]:
    bot = ctx.bot
    name = ctx.text("command", max_length=120).strip().lstrip("/")
    values = clean_values(ctx.args.get("values"))
    channel = resolve_channel(ctx, "send")
    guild = getattr(channel, "guild", None)
    prefix = (await bot.guild_prefix(guild.id if guild else None))[0]
    command = bot.get_command(name)
    app = None if command is not None else _find_app(bot, name)
    if command is None and app is None:
        raise ActionError("The bot has no command with that name.")
    if command is not None:
        text = build_invocation(prefix, command, values)
        shown = text
        arguments = ""
    else:
        assert app is not None
        arguments = build_app_arguments(app, values)
        root = app.root_parent or app
        text = f"{prefix}{root.name}"
        shown = f"/{root.name} {arguments}".strip()

    who = str(ctx.user.get("name") or "a dashboard user")[:60]
    visible = shown.replace("`", "'")[:1800]
    rights = "with owner rights" if as_owner else "as an ordinary member"
    marker = await channel.send(
        f"`{visible}`\n-# Run from the dashboard by {discord.utils.escape_markdown(who)}, {rights}",
        allowed_mentions=discord.AllowedMentions.none())
    fake = copy.copy(marker)
    fake.content = text
    if not as_owner:
        fake.author = ordinary_member(marker.author)
    token = ACTING_AS_OWNER.set(as_owner)
    try:
        cctx = make_context(bot, fake, prefix)
        if command is not None and cctx.command is None:
            with contextlib.suppress(discord.HTTPException):
                await marker.delete()
            raise ActionError("The bot could not read that as a command.")

        async def runner() -> None:
            if command is not None:
                await bot.invoke(cctx)
                return
            assert app is not None
            try:
                await run_app_command(cctx, app.root_parent or app, arguments)
            except commands.CommandError as exc:
                cctx.command_failed = True
                await bot.on_command_error(cctx, exc)
            except Exception as exc:
                cctx.command_failed = True
                await bot.on_command_error(cctx, commands.CommandInvokeError(exc))

        task = asyncio.create_task(runner(), name="zdbf-dashboard-command")
    finally:
        ACTING_AS_OWNER.reset(token)
    task.add_done_callback(_consume)
    done, _ = await asyncio.wait({task}, timeout=WAIT_SECONDS)
    if done and cctx.command_failed and not cctx.captured:
        await asyncio.sleep(1.0)
    me = bot.user.id if bot.user else None
    return {
        "ran": shown,
        "channel": channel_brief(channel),
        "failed": bool(cctx.command_failed),
        "pending": not done,
        "as_owner": as_owner,
        "messages": [serialize_message(m, me) for m in cctx.captured[:MAX_RESULTS]],
        "url": marker.jump_url,
    }


def _summary(args: dict[str, Any]) -> str:
    values = args.get("values") if isinstance(args.get("values"), dict) else {}
    shown = " ".join(f"{k}={str(v)[:60]}" for k, v in list(values.items())[:8])
    return f"run `{str(args.get('command'))[:80]}` {shown} in channel {args.get('channel_id')}".strip()


@action("commands.list", "view", timeout=30)
async def list_commands(ctx: ActionContext) -> dict[str, Any]:
    return {"commands": describe_commands(ctx.bot), "prefix": ctx.bot.config.settings.bot.prefix}


@action("commands.channels", "view", timeout=30)
async def channels(ctx: ActionContext) -> dict[str, Any]:
    tree = build_tree(ctx.bot)
    for guild in tree["guilds"]:
        guild["channels"] = [c for c in guild["channels"] if c["send"]]
        guild["threads"] = [t for t in guild["threads"] if t["send"] and not t["archived"]]
    tree["guilds"] = [g for g in tree["guilds"] if g["channels"] or g["threads"]]
    return tree


@action("commands.run", "commands.run", timeout=WAIT_SECONDS + 20, summary=_summary)
@discord_errors
async def run(ctx: ActionContext) -> dict[str, Any]:
    return await _run(ctx, as_owner=False)


@action("commands.run_owner", "commands.owner", timeout=WAIT_SECONDS + 20, summary=_summary)
@discord_errors
async def run_owner(ctx: ActionContext) -> dict[str, Any]:
    return await _run(ctx, as_owner=True)
