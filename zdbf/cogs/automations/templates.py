# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import contextlib
import datetime as dt
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import aiohttp
import discord

from ...ui import cards
from .engine import Automation, check_url, member_values, render

if TYPE_CHECKING:
    from .cog import Automations

ParamKind = Literal["channel", "role", "roles", "text", "textarea", "number", "bool", "choice", "json", "actions"]
Handler = Callable[..., Awaitable[None]]

__all__ = ["TEMPLATES", "Param", "Runtime", "Template", "level_for_xp", "xp_for_level"]


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    kind: ParamKind
    required: bool = False
    default: Any = None
    description: str = ""
    choices: tuple[str, ...] = ()
    channel_types: tuple[discord.ChannelType, ...] = (discord.ChannelType.text, discord.ChannelType.news)
    show_if: tuple[str, tuple[str, ...]] | None = None

    def visible(self, config: dict[str, Any]) -> bool:
        if self.show_if is None:
            return True
        key, allowed = self.show_if
        return str(config.get(key)) in allowed


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    description: str
    params: tuple[Param, ...]
    handlers: dict[str, Handler] = field(default_factory=dict)
    on_create: Handler | None = None
    on_delete: Handler | None = None
    accepts: Callable[[Automation, str, dict[str, Any]], bool] | None = None
    validate: Callable[[dict[str, Any]], list[str]] | None = None
    timeout: float = 15
    background: bool = False

    def defaults(self) -> dict[str, Any]:
        return {p.key: p.default for p in self.params if p.default is not None}

    def visible(self, config: dict[str, Any]) -> list[Param]:
        return [p for p in self.params if p.visible(config)]

    def missing(self, config: dict[str, Any]) -> list[Param]:
        return [p for p in self.visible(config) if p.required and config.get(p.key) in (None, "", [])]

    def problems(self, config: dict[str, Any]) -> list[str]:
        return self.validate(config) if self.validate else []


class Runtime:
    def __init__(self, cog: Automations) -> None:
        self.cog = cog
        self.bot = cog.bot
        self._last_call: dict[str, float] = {}

    async def state_get(self, auto: Automation, scope: int, key: str, default: Any = None) -> Any:
        raw = await self.bot.db.fetchval(
            "SELECT value FROM automation_state WHERE hook_id = ? AND scope_id = ? AND key = ?",
            (auto.hook_id, scope, key))
        return default if raw is None else json.loads(raw)

    async def state_set(self, auto: Automation, scope: int, key: str, value: Any) -> None:
        await self.bot.db.execute(
            "INSERT INTO automation_state (hook_id, scope_id, key, value) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(hook_id, scope_id, key) DO UPDATE SET value = excluded.value",
            (auto.hook_id, scope, key, json.dumps(value)))

    async def state_delete(self, auto: Automation, scope: int, key: str) -> None:
        await self.bot.db.execute("DELETE FROM automation_state WHERE hook_id = ? AND scope_id = ? AND key = ?",
                                  (auto.hook_id, scope, key))

    def channel(self, value: Any) -> Any:
        with contextlib.suppress(TypeError, ValueError):
            return self.bot.get_channel(int(value))
        return None

    def prune(self, older_than: float = 7 * 24 * 3600) -> None:
        cutoff = time.monotonic() - older_than
        self._last_call = {k: v for k, v in self._last_call.items() if v >= cutoff}

    def throttle(self, key: str, seconds: float) -> bool:
        now = time.monotonic()
        last = self._last_call.get(key)
        if last is not None and now - last < seconds:
            return False
        self._last_call[key] = now
        return True

    async def send(self, channel: Any, text: str, *, card: bool, title: str | None = None,
                   accent: Any = None, thumbnail: str | None = None) -> discord.Message | None:
        if not isinstance(channel, discord.abc.Messageable):
            return None
        mentions = discord.AllowedMentions(everyone=False, roles=False, users=True)
        if not card:
            return await channel.send(cards.truncate(text, 2000), allowed_mentions=mentions)
        colour = _colour(accent)
        box = cards.card(title, text, accent=colour or "primary", thumbnail=thumbnail) if title else \
            cards.container(cards.section(text, discord.ui.Thumbnail(thumbnail)) if thumbnail else text,
                            accent=colour or "primary")
        return await channel.send(view=cards.static(box), allowed_mentions=mentions)


def _colour(value: Any) -> discord.Colour | None:
    if not value:
        return None
    with contextlib.suppress(ValueError):
        return discord.Colour(int(str(value).lstrip("#"), 16))
    return None


def _ids(value: Any) -> list[int]:
    if isinstance(value, list):
        return [int(v) for v in value if str(v).isdigit()]
    if isinstance(value, str):
        return [int(v) for v in re.findall(r"\d{15,21}", value)]
    if isinstance(value, int):
        return [value]
    return []


def level_for_xp(xp: int) -> int:
    return int((max(xp, 0) / 50) ** 0.5)


def xp_for_level(level: int) -> int:
    return 50 * level * level


async def _welcome(rt: Runtime, auto: Automation, member: discord.Member) -> None:
    c = auto.config
    values = member_values(member, member.guild)
    if channel := rt.channel(c.get("channel_id")):
        await rt.send(channel, render(c.get("message", "Welcome, {user}."), **values), card=c.get("card", True),
                      title=render(c.get("title") or "", **values) or None, accent=c.get("color"),
                      thumbnail=member.display_avatar.url if c.get("card", True) else None)
    if role_id := c.get("auto_role_id"):
        role = member.guild.get_role(int(role_id))
        if role and role < member.guild.me.top_role:
            await member.add_roles(role, reason=f"Automation: {auto.name}")
    if c.get("send_dm") and c.get("dm_message"):
        with contextlib.suppress(discord.HTTPException):
            await member.send(render(c["dm_message"], **values)[:2000])


async def _goodbye(rt: Runtime, auto: Automation, member: discord.Member) -> None:
    c = auto.config
    if channel := rt.channel(c.get("channel_id")):
        await rt.send(channel, render(c.get("message", "{username} left the server."),
                                      **member_values(member, member.guild)),
                      card=c.get("card", True), accent=c.get("color") or "ED4245")


def _emoji_key(emoji: discord.PartialEmoji) -> list[str]:
    return [str(emoji), emoji.name or "", str(emoji.id or "")]


async def _reaction_role(rt: Runtime, auto: Automation, payload: discord.RawReactionActionEvent,
                         *, added: bool) -> None:
    c = auto.config
    if str(payload.message_id) != str(c.get("message_id")) or payload.guild_id is None:
        return
    if not added and not c.get("remove_on_unreact", True):
        return
    mapping = c.get("mapping") or {}
    if isinstance(mapping, str):
        mapping = json.loads(mapping)
    role_id = next((mapping[k] for k in _emoji_key(payload.emoji) if k in mapping), None)
    guild = rt.bot.get_guild(payload.guild_id)
    if role_id is None or guild is None:
        return
    member = payload.member or guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
    role = guild.get_role(int(role_id))
    if member is None or member.bot or role is None:
        return
    if added:
        await member.add_roles(role, reason=f"Reaction role: {auto.name}")
    else:
        await member.remove_roles(role, reason=f"Reaction role: {auto.name}")


async def _reaction_add(rt: Runtime, auto: Automation, payload: discord.RawReactionActionEvent) -> None:
    await _reaction_role(rt, auto, payload, added=True)


async def _reaction_remove(rt: Runtime, auto: Automation, payload: discord.RawReactionActionEvent) -> None:
    await _reaction_role(rt, auto, payload, added=False)


def button_roles_panel(auto: Automation, guild: discord.Guild) -> cards.StaticView:
    from .persistent import RoleButton

    c = auto.config
    roles = [r for r in (guild.get_role(i) for i in _ids(c.get("roles"))) if r is not None][:20]
    box = cards.card(c.get("title") or "Pick your roles", c.get("description") or "Click a button to toggle a role.",
                     accent=_colour(c.get("color")) or "primary")
    for start in range(0, len(roles), 5):
        box.add_item(discord.ui.ActionRow(*[RoleButton(auto.hook_id, r.id, r.name) for r in roles[start:start + 5]]))
    if not roles:
        box.add_item(cards.text("-# No roles configured."))
    return cards.static(box)


async def _post_panel(rt: Runtime, auto: Automation, builder: Callable[[Automation, discord.Guild], Any]) -> None:
    guild = rt.bot.get_guild(auto.guild_id)
    channel = rt.channel(auto.config.get("channel_id"))
    if guild is None or not isinstance(channel, discord.abc.Messageable):
        raise RuntimeError("panel channel not found")
    old_id = auto.config.get("panel_message_id")
    view = builder(auto, guild)
    if old_id:
        with contextlib.suppress(discord.HTTPException):
            msg = await channel.fetch_message(int(old_id))  # type: ignore[union-attr]
            await msg.edit(view=view)
            return
    msg = await channel.send(view=view)
    auto.config["panel_message_id"] = msg.id


async def _delete_panel(rt: Runtime, auto: Automation) -> None:
    channel = rt.channel(auto.config.get("channel_id"))
    if channel and auto.config.get("panel_message_id"):
        with contextlib.suppress(discord.HTTPException):
            msg = await channel.fetch_message(int(auto.config["panel_message_id"]))
            await msg.delete()


async def _button_roles_create(rt: Runtime, auto: Automation) -> None:
    await _post_panel(rt, auto, button_roles_panel)


async def _automod(rt: Runtime, auto: Automation, message: discord.Message) -> None:
    c = auto.config
    member = message.author
    if not isinstance(member, discord.Member) or member.bot:
        return
    if member.guild_permissions.manage_messages or {r.id for r in member.roles} & set(_ids(c.get("ignore_roles"))):
        return
    words = [w.strip() for w in re.split(r"[,\n]", c.get("words", "")) if w.strip()]
    if not words:
        return
    flags = 0 if c.get("case_sensitive") else re.IGNORECASE
    pattern = "|".join(re.escape(w) for w in words)
    if c.get("whole_word", True):
        pattern = rf"\b(?:{pattern})\b"
    hit = re.search(pattern, message.content, flags)
    if hit is None:
        return
    action = c.get("action", "delete")
    with contextlib.suppress(discord.HTTPException):
        if action != "log_only":
            await message.delete()
        if action == "delete_warn":
            await message.channel.send(f"{member.mention}, that word isn't allowed here.", delete_after=8)
        elif action == "timeout":
            await member.timeout(dt.timedelta(seconds=int(c.get("timeout_seconds", 300))),
                                 reason=f"Automod: {auto.name}")
        elif action == "kick":
            await member.kick(reason=f"Automod: {auto.name}")
    if log_channel := rt.channel(c.get("log_channel_id")):
        await rt.send(log_channel, cards.kv({
            "Member": f"{member.mention} (`{member.id}`)", "Channel": message.channel.mention,  # type: ignore[union-attr]
            "Matched": f"`{hit.group(0)}`", "Action": action,
            "Message": cards.truncate(message.content, 500)}), card=True, title="Automod", accent="ED4245")


async def _leveling(rt: Runtime, auto: Automation, message: discord.Message) -> None:
    c = auto.config
    author = message.author
    if author.bot or message.guild is None:
        return
    if not rt.throttle(f"{auto.hook_id}:{author.id}", float(c.get("cooldown", 60))):
        return
    xp = int(await rt.state_get(auto, author.id, "xp", 0)) + int(c.get("xp_per_message", 10))
    old_level = level_for_xp(xp - int(c.get("xp_per_message", 10)))
    await rt.state_set(auto, author.id, "xp", xp)
    level = level_for_xp(xp)
    if level <= old_level:
        return
    values = {**member_values(author, message.guild), "level": level, "xp": xp}
    target = rt.channel(c.get("levelup_channel_id")) or message.channel
    await rt.send(target, render(c.get("levelup_message", "{user} reached level **{level}**."), **values),
                  card=c.get("card", True), accent="F1C40F")
    rewards = c.get("role_rewards") or {}
    if isinstance(rewards, str):
        rewards = json.loads(rewards or "{}")
    if (role_id := rewards.get(str(level))) and isinstance(author, discord.Member):
        role = message.guild.get_role(int(role_id))
        if role and role < message.guild.me.top_role:
            await author.add_roles(role, reason=f"Level {level} reward")


async def _announce_tick(rt: Runtime, auto: Automation) -> None:
    c = auto.config
    hours = float(c.get("interval_hours", 24))
    last = float(await rt.state_get(auto, 0, "last_sent", 0))
    if time.time() - last < hours * 3600:
        return
    await rt.state_set(auto, 0, "last_sent", time.time())
    if channel := rt.channel(c.get("channel_id")):
        await rt.send(channel, c.get("message", ""), card=c.get("card", True), title=c.get("title") or None,
                      accent=c.get("color"))


def ticket_panel(auto: Automation, guild: discord.Guild) -> cards.StaticView:
    from .persistent import TicketOpenButton

    c = auto.config
    box = cards.card(c.get("title") or "Support", c.get("description") or "Need help? Open a private ticket below.", accent=_colour(c.get("color")) or "primary")
    box.add_item(discord.ui.ActionRow(TicketOpenButton(auto.hook_id)))
    return cards.static(box)


async def _tickets_create(rt: Runtime, auto: Automation) -> None:
    await _post_panel(rt, auto, ticket_panel)


async def _voice_log(rt: Runtime, auto: Automation, member: discord.Member, before: discord.VoiceState,
                     after: discord.VoiceState) -> None:
    c = auto.config
    channel = rt.channel(c.get("channel_id"))
    if channel is None:
        return
    line = None
    if before.channel is None and after.channel and c.get("log_joins", True):
        line = f"{member.mention} joined {after.channel.mention}"
    elif after.channel is None and before.channel and c.get("log_leaves", True):
        line = f"{member.mention} left {before.channel.mention}"
    elif before.channel and after.channel and before.channel != after.channel and c.get("log_moves", True):
        line = f"{member.mention} moved {before.channel.mention} → {after.channel.mention}"
    elif c.get("log_mutes") and (before.self_mute != after.self_mute or before.mute != after.mute):
        line = f"{member.mention} {'muted' if after.self_mute or after.mute else 'unmuted'}"
    if line:
        await rt.send(channel, f"{line} · {cards.timestamp(style='T')}", card=False)


async def _dynamic_voice(rt: Runtime, auto: Automation, member: discord.Member, before: discord.VoiceState,
                         after: discord.VoiceState) -> None:
    c = auto.config
    hub_id = int(c.get("hub_channel_id") or 0)
    if after.channel and after.channel.id == hub_id:
        hub = after.channel
        category = rt.channel(c.get("category_id")) or hub.category
        name = render(c.get("name_template", "{display_name}'s channel"), **member_values(member, member.guild))[:100]
        new = await member.guild.create_voice_channel(
            name, category=category if isinstance(category, discord.CategoryChannel) else None,
            user_limit=int(c.get("user_limit") or 0), reason=f"Dynamic voice: {auto.name}",
            overwrites={member: discord.PermissionOverwrite(manage_channels=True, move_members=True)})
        await rt.state_set(auto, new.id, "temp", member.id)
        with contextlib.suppress(discord.HTTPException):
            await member.move_to(new)
    if before.channel and before.channel.id != hub_id and not before.channel.members:
        if await rt.state_get(auto, before.channel.id, "temp") is not None:
            await rt.state_delete(auto, before.channel.id, "temp")
            with contextlib.suppress(discord.HTTPException):
                await before.channel.delete(reason="Dynamic voice channel empty")


async def _webhook(rt: Runtime, auto: Automation, payload: dict[str, Any]) -> None:
    url = str(auto.config.get("webhook_url", ""))
    if err := check_url(url):
        raise RuntimeError(f"webhook URL rejected: {err}")
    if not rt.throttle(f"wh:{auto.hook_id}", 1.0):
        return
    is_discord = "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url
    body = {"content": cards.truncate(payload.get("summary", ""), 2000), "allowed_mentions": {"parse": []}} \
        if is_discord else payload
    session = await rt.cog.http()
    async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"webhook responded {resp.status}")


async def _webhook_message(rt: Runtime, auto: Automation, message: discord.Message) -> None:
    if message.author.bot or "message" not in auto.config.get("events", "message,member_join"):
        return
    channels = _ids(auto.config.get("channel_ids"))
    if channels and message.channel.id not in channels:
        return
    content = message.content if auto.config.get("include_content", True) else ""
    await _webhook(rt, auto, {"event": "message", "guild_id": message.guild.id if message.guild else None,
                              "channel_id": message.channel.id, "author_id": message.author.id,
                              "author": str(message.author), "content": content,
                              "timestamp": message.created_at.isoformat(),
                              "summary": f"**{message.author}** in #{getattr(message.channel, 'name', '?')}: {content}"})


async def _webhook_join(rt: Runtime, auto: Automation, member: discord.Member) -> None:
    if "member_join" not in auto.config.get("events", "message,member_join"):
        return
    await _webhook(rt, auto, {"event": "member_join", "guild_id": member.guild.id, "user_id": member.id,
                              "user": str(member), "timestamp": dt.datetime.now(dt.UTC).isoformat(),
                              "summary": f"**{member}** joined {member.guild.name}"})


TEXT = (discord.ChannelType.text, discord.ChannelType.news)
VOICE = (discord.ChannelType.voice,)
CATEGORY = (discord.ChannelType.category,)

TEMPLATES: dict[str, Template] = {t.id: t for t in (
    Template(
        "welcome", "Welcome", "Greet new members with a card, give them a role and optionally DM them.",
        (
            Param("channel_id", "Welcome channel", "channel", True),
            Param("message", "Message", "textarea", True, "Welcome to **{guild_name}**, {user}. You are member #{member_count}.",
                  "Variables: {user} {username} {display_name} {guild_name} {member_count}"),
            Param("title", "Card title", "text", False, "Welcome"),
            Param("card", "Send as card", "bool", False, True),
            Param("color", "Accent colour (hex)", "text", False, "5865F2"),
            Param("auto_role_id", "Auto role", "role"),
            Param("send_dm", "Also DM the member", "bool", False, False),
            Param("dm_message", "DM text", "textarea", False, "Welcome to {guild_name}, {display_name}."),
        ),
        {"member_join": _welcome},
    ),
    Template(
        "goodbye", "Goodbye", "Post a farewell when members leave.",
        (
            Param("channel_id", "Goodbye channel", "channel", True),
            Param("message", "Message", "textarea", True, "**{username}** left the server. We're now {member_count}."),
            Param("card", "Send as card", "bool", False, True),
            Param("color", "Accent colour (hex)", "text", False, "ED4245"),
        ),
        {"member_remove": _goodbye},
    ),
    Template(
        "button_roles", "Button roles", "A panel with buttons members click to toggle roles. Survives restarts.",
        (
            Param("channel_id", "Panel channel", "channel", True),
            Param("roles", "Roles", "roles", True, description="Up to 20 roles"),
            Param("title", "Panel title", "text", False, "Pick your roles"),
            Param("description", "Panel text", "textarea", False, "Click a button to add or remove a role."),
            Param("exclusive", "Only one role at a time", "bool", False, False),
            Param("color", "Accent colour (hex)", "text"),
        ),
        {}, on_create=_button_roles_create, on_delete=_delete_panel,
    ),
    Template(
        "reaction_roles", "Reaction roles", "Classic reaction roles on an existing message.",
        (
            Param("channel_id", "Channel of the message", "channel", True),
            Param("message_id", "Message ID", "text", True),
            Param("mapping", "Emoji → role ID (JSON)", "json", True, '{"👍": "ROLE_ID"}'),
            Param("remove_on_unreact", "Remove role on un-react", "bool", False, True),
        ),
        {"reaction_add": _reaction_add, "reaction_remove": _reaction_remove},
    ),
    Template(
        "automod", "Word filter", "Delete, warn, timeout or kick when banned words are used.",
        (
            Param("words", "Banned words", "textarea", True, description="Comma or newline separated"),
            Param("action", "Action", "choice", True, "delete",
                  choices=("delete", "delete_warn", "timeout", "kick", "log_only")),
            Param("timeout_seconds", "Timeout seconds", "number", False, 300),
            Param("log_channel_id", "Log channel", "channel"),
            Param("ignore_roles", "Ignored roles", "roles"),
            Param("whole_word", "Whole words only", "bool", False, True),
            Param("case_sensitive", "Case sensitive", "bool", False, False),
        ),
        {"message": _automod},
    ),
    Template(
        "leveling", "XP & levels", "Award XP for chatting, announce level-ups and give reward roles.",
        (
            Param("xp_per_message", "XP per message", "number", True, 10),
            Param("cooldown", "Cooldown seconds", "number", False, 60),
            Param("levelup_channel_id", "Level-up channel", "channel", description="Defaults to the chat channel"),
            Param("levelup_message", "Level-up message", "textarea", False, "{user} reached level **{level}**."),
            Param("role_rewards", "Role rewards (JSON level → role ID)", "json", False, "{}"),
            Param("card", "Send as card", "bool", False, True),
        ),
        {"message": _leveling},
    ),
    Template(
        "announcements", "Recurring announcement", "Post a message every N hours.",
        (
            Param("channel_id", "Channel", "channel", True),
            Param("message", "Message", "textarea", True),
            Param("interval_hours", "Every N hours", "number", True, 24),
            Param("title", "Title", "text"),
            Param("card", "Send as card", "bool", False, True),
            Param("color", "Accent colour (hex)", "text"),
        ),
        {"tick": _announce_tick},
    ),
    Template(
        "tickets", "Support tickets", "A panel with an 'Open ticket' button that creates private channels.",
        (
            Param("channel_id", "Panel channel", "channel", True),
            Param("category_id", "Ticket category", "channel", channel_types=CATEGORY),
            Param("support_role_id", "Support role", "role", True),
            Param("name_template", "Channel name", "text", False, "ticket-{username}"),
            Param("title", "Panel title", "text", False, "Support"),
            Param("description", "Panel text", "textarea", False, "Need help? Open a private ticket below."),
            Param("welcome", "Ticket welcome", "textarea", False,
                  "Hi {user}, describe your issue and the team will be with you shortly."),
        ),
        {}, on_create=_tickets_create, on_delete=_delete_panel,
    ),
    Template(
        "voice_log", "Voice activity log", "Log voice joins, leaves, moves and mutes.",
        (
            Param("channel_id", "Log channel", "channel", True),
            Param("log_joins", "Log joins", "bool", False, True),
            Param("log_leaves", "Log leaves", "bool", False, True),
            Param("log_moves", "Log moves", "bool", False, True),
            Param("log_mutes", "Log mutes", "bool", False, False),
        ),
        {"voice": _voice_log},
    ),
    Template(
        "dynamic_voice", "Join-to-create voice", "Joining a hub channel creates a personal voice channel.",
        (
            Param("hub_channel_id", "Hub voice channel", "channel", True, channel_types=VOICE),
            Param("category_id", "Category", "channel", channel_types=CATEGORY),
            Param("name_template", "Channel name", "text", False, "{display_name}'s channel"),
            Param("user_limit", "User limit (0 = none)", "number", False, 0),
        ),
        {"voice": _dynamic_voice},
    ),
    Template(
        "webhook_bridge", "Webhook bridge", "Forward messages / joins to an external webhook (Zapier, Make, Discord…).",
        (
            Param("webhook_url", "Webhook URL (https)", "text", True),
            Param("events", "Events", "choice", True, "message,member_join",
                  choices=("message", "member_join", "message,member_join")),
            Param("channel_ids", "Only these channels (IDs)", "text", description="Optional, comma separated"),
            Param("include_content", "Include message content", "bool", False, True),
        ),
        {"message": _webhook_message, "member_join": _webhook_join},
    ),
)}
