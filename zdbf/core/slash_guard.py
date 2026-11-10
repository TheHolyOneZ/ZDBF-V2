# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import contextlib
import datetime as dt
import logging
import shlex
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from .bot import ZDBFBot

__all__ = ["SLASH_LIMIT", "Demotion", "GuardedTree", "PrefixInteraction", "SlashGuard", "run_app_command"]

log = logging.getLogger("zdbf.slash_guard")
SLASH_LIMIT = 100
AppCommand = app_commands.Command[Any, ..., Any] | app_commands.Group


@dataclass(frozen=True)
class Demotion:
    name: str
    scope: str
    kind: str
    source: str
    fallback: bool


class _Response:
    def __init__(self, owner: PrefixInteraction) -> None:
        self._owner = owner
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, *, ephemeral: bool = False, thinking: bool = False) -> None:
        self._done = True
        with contextlib.suppress(discord.HTTPException):
            await self._owner._ctx.typing()

    async def send_message(self, content: Any = None, **kwargs: Any) -> None:
        self._done = True
        await self._owner._send(content, **kwargs)

    async def edit_message(self, *, content: Any = None, **kwargs: Any) -> None:
        self._done = True
        await self._owner.edit_original_response(content=content, **kwargs)

    async def send_modal(self, modal: discord.ui.Modal) -> None:
        self._done = True
        await self._owner._send("This command opens a dialog, which only works as a slash command. "
                                "The bot has more than 100 slash commands, so this one is only available "
                                "with the prefix right now.")

    async def pong(self) -> None:
        self._done = True


class _Followup:
    def __init__(self, owner: PrefixInteraction) -> None:
        self._owner = owner

    async def send(self, content: Any = None, **kwargs: Any) -> discord.Message | None:
        return await self._owner._send(content, **kwargs)


class PrefixInteraction:
    _SEND_KWARGS = ("embed", "embeds", "file", "files", "view", "allowed_mentions", "delete_after", "silent",
                    "suppress_embeds", "stickers")

    def __init__(self, ctx: commands.Context[Any], command: AppCommand) -> None:
        self._ctx = ctx
        self._last: discord.Message | None = None
        self.client = ctx.bot
        self.command = command
        self.user = ctx.author
        self.guild = ctx.guild
        self.guild_id = ctx.guild.id if ctx.guild else None
        self.channel = ctx.channel
        self.channel_id = ctx.channel.id
        self.message = ctx.message
        self.id = ctx.message.id
        self.type = discord.InteractionType.application_command
        self.created_at = ctx.message.created_at
        self.locale = discord.Locale.american_english
        self.guild_locale = getattr(ctx.guild, "preferred_locale", None)
        self.extras: dict[str, Any] = {"zdbf_prefix_fallback": True}
        self.namespace: Any = SimpleNamespace()
        self.response = _Response(self)
        self.followup = _Followup(self)
        self.data: dict[str, Any] = {}

    @property
    def permissions(self) -> discord.Permissions:
        if isinstance(self.user, discord.Member) and hasattr(self.channel, "permissions_for"):
            return self.channel.permissions_for(self.user)  # type: ignore[union-attr]
        return discord.Permissions.none()

    @property
    def app_permissions(self) -> discord.Permissions:
        me = self.guild.me if self.guild else None
        if me is not None and hasattr(self.channel, "permissions_for"):
            return self.channel.permissions_for(me)  # type: ignore[union-attr]
        return discord.Permissions.none()

    def is_expired(self) -> bool:
        return False

    async def _send(self, content: Any = None, **kwargs: Any) -> discord.Message | None:
        kwargs.pop("ephemeral", None)
        kwargs.pop("thinking", None)
        clean = {k: v for k, v in kwargs.items() if k in self._SEND_KWARGS and v is not None}
        if clean.get("view") is discord.utils.MISSING:
            clean.pop("view")
        self._last = await self._ctx.send(content, **clean)
        return self._last

    async def original_response(self) -> discord.Message:
        if self._last is None:
            raise discord.NotFound(_FakeResponse(), "no response yet")  # type: ignore[arg-type]
        return self._last

    async def edit_original_response(self, **kwargs: Any) -> discord.Message | None:
        if self._last is None:
            return await self._send(**kwargs)
        clean = {k: v for k, v in kwargs.items() if k in ("content", "embed", "embeds", "view", "attachments",
                                                           "allowed_mentions")}
        self._last = await self._last.edit(**clean)
        return self._last

    async def delete_original_response(self) -> None:
        if self._last is not None:
            with contextlib.suppress(discord.HTTPException):
                await self._last.delete()


class _FakeResponse:
    status = 404
    reason = "Not Found"


_BOOL = {"true": True, "yes": True, "on": True, "1": True, "y": True,
         "false": False, "no": False, "off": False, "0": False, "n": False}


async def _convert(ctx: commands.Context[Any], param: Any, raw: str) -> Any:
    kind = param.type
    if param.choices:
        for choice in param.choices:
            if raw.lower() in (str(choice.name).lower(), str(choice.value).lower()):
                return choice.value if not param.is_choice_annotation() else choice
        raise commands.BadArgument(f"{param.display_name} must be one of: "
                                   + ", ".join(str(c.name) for c in param.choices))
    match kind:
        case discord.AppCommandOptionType.integer:
            value: Any = int(raw)
        case discord.AppCommandOptionType.number:
            value = float(raw)
        case discord.AppCommandOptionType.boolean:
            if raw.lower() not in _BOOL:
                raise commands.BadArgument(f"{param.display_name} must be yes or no")
            return _BOOL[raw.lower()]
        case discord.AppCommandOptionType.user:
            try:
                return await commands.MemberConverter().convert(ctx, raw)
            except commands.BadArgument:
                return await commands.UserConverter().convert(ctx, raw)
        case discord.AppCommandOptionType.channel:
            return await commands.GuildChannelConverter().convert(ctx, raw)
        case discord.AppCommandOptionType.role:
            return await commands.RoleConverter().convert(ctx, raw)
        case discord.AppCommandOptionType.mentionable:
            try:
                return await commands.MemberConverter().convert(ctx, raw)
            except commands.BadArgument:
                return await commands.RoleConverter().convert(ctx, raw)
        case _:
            value = raw
    if isinstance(value, int | float) and not isinstance(value, bool):
        if param.min_value is not None and value < param.min_value:
            raise commands.BadArgument(f"{param.display_name} must be at least {param.min_value}")
        if param.max_value is not None and value > param.max_value:
            raise commands.BadArgument(f"{param.display_name} must be at most {param.max_value}")
    if isinstance(value, str):
        if param.min_value is not None and len(value) < param.min_value:
            raise commands.BadArgument(f"{param.display_name} must be at least {param.min_value} characters")
        if param.max_value is not None and len(value) > param.max_value:
            raise commands.BadArgument(f"{param.display_name} must be at most {param.max_value} characters")
    return value


async def run_app_command(ctx: commands.Context[Any], root: AppCommand, args: str) -> None:
    try:
        tokens = shlex.split(args)
    except ValueError:
        tokens = args.split()
    target: Any = root
    path = [root.name]
    while isinstance(target, app_commands.Group):
        sub = target.get_command(tokens[0]) if tokens else None
        if sub is None:
            names = ", ".join(f"`{c.name}`" for c in target.commands) or "none"
            await ctx.send(f"Usage: `{ctx.clean_prefix}{' '.join(path)} <subcommand>` · subcommands: {names}")
            return
        tokens.pop(0)
        path.append(sub.name)
        target = sub
    command: app_commands.Command[Any, ..., Any] = target
    if command.guild_only and ctx.guild is None:
        raise commands.NoPrivateMessage()
    needed = command.default_permissions or root.default_permissions
    if needed is not None and isinstance(ctx.author, discord.Member) and \
            not ctx.author.guild_permissions.is_superset(needed) and not await ctx.bot.is_owner(ctx.author):
        raise commands.MissingPermissions([p for p, v in needed if v])
    interaction = PrefixInteraction(ctx, command)
    kwargs: dict[str, Any] = {}
    interaction.namespace = SimpleNamespace(**{p.name: None for p in command.parameters})
    params = list(command.parameters)
    for i, param in enumerate(params):
        if not tokens:
            if param.required:
                raise commands.BadArgument(f"missing argument `{param.display_name}`")
            kwargs[param.name] = param.default if param.default is not discord.utils.MISSING else None
            continue
        if param.type is discord.AppCommandOptionType.attachment:
            index = sum(1 for p in params[:i] if p.type is discord.AppCommandOptionType.attachment)
            if index >= len(ctx.message.attachments):
                raise commands.BadArgument(f"attach a file for `{param.display_name}`")
            kwargs[param.name] = ctx.message.attachments[index]
            continue
        last_string = i == len(params) - 1 and param.type is discord.AppCommandOptionType.string
        raw = " ".join(tokens) if last_string else tokens.pop(0)
        if last_string:
            tokens = []
        try:
            kwargs[param.name] = await _convert(ctx, param, raw)
        except ValueError as exc:
            raise commands.BadArgument(f"`{param.display_name}`: {exc}") from exc
        setattr(interaction.namespace, param.name, kwargs[param.name])
    for check in [*getattr(root, "checks", ()), *command.checks]:
        result = check(interaction)  # type: ignore[arg-type]
        if hasattr(result, "__await__"):
            result = await result
        if not result:
            raise commands.CheckFailure("you cannot use this command")
    binding = command.binding
    if binding is not None:
        await command.callback(binding, interaction, **kwargs)  # type: ignore[arg-type,call-arg]
    else:
        await command.callback(interaction, **kwargs)  # type: ignore[arg-type,call-arg]


class SlashGuard:
    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.demoted: dict[tuple[str, str], Demotion] = {}
        self._stash: dict[tuple[str, str], AppCommand] = {}
        self._fallbacks: dict[str, commands.Command[Any, ..., Any]] = {}
        self.last_run: dt.datetime | None = None
        self.newly_demoted: list[str] = []

    def _source(self, cmd: AppCommand) -> str:
        return str(getattr(cmd, "module", "") or "")

    def _priority(self, cmd: AppCommand, order: int) -> tuple[int, int, int]:
        module = self._source(cmd)
        if module.startswith("zdbf."):
            return (0, 0, order)
        for index, ext in enumerate(self.bot.extensions):
            if module == ext or module.startswith(ext + "."):
                return (1, index, order)
        return (2, 0, order)

    def _alive(self, cmd: AppCommand) -> bool:
        if any(getattr(c, "app_command", None) is cmd for c in self.bot.commands):
            return True
        binding = getattr(cmd, "binding", None)
        if isinstance(binding, commands.Cog):
            return binding in self.bot.cogs.values()
        module = self._source(cmd)
        return module.startswith("zdbf.") or module in sys.modules

    def _hybrid_names(self) -> set[str]:
        return {c.app_command.name for c in self.bot.commands
                if getattr(c, "app_command", None) is not None and getattr(c, "with_app_command", True)}

    def overflow(self, cmd: AppCommand, guild: discord.abc.Snowflake | None) -> None:
        scope = "global" if guild is None else str(guild.id)
        self._stash[(scope, cmd.name)] = cmd
        is_hybrid = cmd.name in self._hybrid_names()
        fallback = is_hybrid or self._add_fallback(cmd)
        self.demoted[(scope, cmd.name)] = Demotion(cmd.name, scope, "hybrid" if is_hybrid else "app",
                                                   self._source(cmd), fallback)
        self.newly_demoted.append(f"/{cmd.name}")
        log.warning("slash command limit reached - /%s (%s) works with the prefix only", cmd.name, self._source(cmd))

    def enforce(self, scopes: list[discord.abc.Snowflake | None], limit: int = SLASH_LIMIT) -> list[Demotion]:
        tree = self.bot.tree
        for name, fallback in list(self._fallbacks.items()):
            if self.bot.get_command(name) is fallback:
                self.bot.remove_command(name)
        self._fallbacks.clear()
        hybrid = self._hybrid_names()
        demoted: dict[tuple[str, str], Demotion] = {}
        stash: dict[tuple[str, str], AppCommand] = {}
        for guild in scopes:
            scope = "global" if guild is None else str(guild.id)
            current = list(tree.get_commands(guild=guild, type=discord.AppCommandType.chat_input))
            names = {c.name for c in current}
            waiting = [c for (sc, n), c in self._stash.items()
                       if sc == scope and n not in names and self._alive(c)]
            candidates = current + waiting
            ranked = [c for _, c in sorted(enumerate(candidates), key=lambda item: self._priority(item[1], item[0]))]
            keep, drop = ranked[:limit], ranked[limit:]
            for cmd in drop:
                if cmd.name in names:
                    tree.remove_command(cmd.name, guild=guild)
            for cmd in keep:
                if cmd.name not in names:
                    tree.add_command(cmd, guild=guild)
            for cmd in drop:
                stash[(scope, cmd.name)] = cmd
                is_hybrid = cmd.name in hybrid
                fallback = is_hybrid or self._add_fallback(cmd)
                demoted[(scope, cmd.name)] = Demotion(cmd.name, scope, "hybrid" if is_hybrid else "app",
                                                      self._source(cmd), fallback)
        for key, cmd in self._stash.items():
            if key[0] not in {("global" if g is None else str(g.id)) for g in scopes} and self._alive(cmd):
                stash[key] = cmd
                demoted[key] = self.demoted.get(key) or Demotion(cmd.name, key[0], "app", self._source(cmd), False)
        new = set(demoted) - set(self.demoted)
        self.newly_demoted = sorted({*self.newly_demoted, *(f"/{name}" for _, name in new)})
        self._stash = stash
        self.demoted = demoted
        self.last_run = dt.datetime.now(dt.UTC)
        return list(demoted.values())

    def _add_fallback(self, cmd: AppCommand) -> bool:
        if cmd.name in self._fallbacks:
            return True
        if self.bot.get_command(cmd.name) is not None:
            return False

        async def fallback(ctx: commands.Context[Any], *, args: str = "") -> None:
            await run_app_command(ctx, cmd, args)

        prefix_cmd: commands.Command[Any, ..., Any] = commands.Command(
            fallback, name=cmd.name, help=f"{cmd.description} (prefix fallback - the slash limit is reached)")
        prefix_cmd.extras["zdbf_slash_fallback"] = True
        self.bot.add_command(prefix_cmd)
        self._fallbacks[cmd.name] = prefix_cmd
        return True


class GuardedTree(app_commands.CommandTree[Any]):
    def add_command(self, command: Any, /, *, guild: discord.abc.Snowflake | None = discord.utils.MISSING,
                    guilds: Any = discord.utils.MISSING, override: bool = False) -> None:
        try:
            super().add_command(command, guild=guild, guilds=guilds, override=override)
        except app_commands.CommandLimitReached:
            guard: SlashGuard | None = getattr(self.client, "slash_guard", None)
            if guard is None or isinstance(command, app_commands.ContextMenu):
                raise
            targets = [None] if guild in (None, discord.utils.MISSING) and guilds is discord.utils.MISSING else \
                ([guild] if guild not in (None, discord.utils.MISSING) else list(guilds))
            for target in targets:
                if self.get_command(command.name, guild=target) is None:
                    with contextlib.suppress(app_commands.CommandLimitReached):
                        super().add_command(command, guild=target, override=override)
                        continue
                    guard.overflow(command, target)
