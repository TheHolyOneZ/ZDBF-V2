# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

import aiohttp
import discord

from ...ui import cards
from .engine import Automation, check_url, member_values, render
from .templates import TEMPLATES, VOICE, Param, Template, _colour

if TYPE_CHECKING:
    from .templates import Runtime

__all__ = ["ACTION_TYPES", "CUSTOM", "MAX_ACTIONS", "MAX_DEPTH", "TRIGGERS", "ActionField", "ActionType",
           "build_context", "check_url", "run_actions", "summarize", "validate_actions"]

MAX_ACTIONS = 15
MAX_DEPTH = 5
MAX_DELAY = 300
MAX_TOTAL_DELAY = 600
MAX_TIMEOUT = 28 * 24 * 3600

FieldKind = Literal["channel", "role", "text", "textarea", "number", "bool", "json", "automation"]

TRIGGERS: dict[str, tuple[str, str]] = {
    "member_join": ("A member joins", "member_join"),
    "member_leave": ("A member leaves", "member_remove"),
    "message": ("A message is sent", "message"),
    "reaction_add": ("A reaction is added", "reaction_add"),
    "voice_join": ("A member joins a voice channel", "voice"),
    "schedule": ("On a schedule", "tick"),
}
MATCH_MODES = ("any", "contains", "exact", "starts_with", "regex")


@dataclass(frozen=True)
class ActionField:
    key: str
    label: str
    kind: FieldKind
    required: bool = False
    default: Any = None
    description: str = ""


@dataclass(frozen=True)
class ActionType:
    id: str
    name: str
    description: str
    fields: tuple[ActionField, ...] = ()
    needs_member: bool = False

    def defaults(self) -> dict[str, Any]:
        return {f.key: f.default for f in self.fields if f.default is not None}


ACTION_TYPES: dict[str, ActionType] = {a.id: a for a in (
    ActionType("send_message", "Send a message", "Post a message, as text or as a card.", (
        ActionField("channel_id", "Channel", "channel", description="Empty = the channel the event happened in"),
        ActionField("message", "Message", "textarea", True, description="Supports all variables"),
        ActionField("title", "Card title", "text"),
        ActionField("card", "Send as card", "bool", default=True),
        ActionField("color", "Accent colour (hex)", "text"),
    )),
    ActionType("send_dm", "Send a DM", "Message the member privately. Closed DMs are skipped silently.", (
        ActionField("message", "Message", "textarea", True),
    ), needs_member=True),
    ActionType("add_role", "Add a role", "Give the member a role.", (
        ActionField("role_id", "Role", "role", True),
    ), needs_member=True),
    ActionType("remove_role", "Remove a role", "Take a role away from the member.", (
        ActionField("role_id", "Role", "role", True),
    ), needs_member=True),
    ActionType("timeout", "Time out", "Time the member out.", (
        ActionField("seconds", "Seconds", "number", True, 60, "Up to 28 days"),
        ActionField("reason", "Reason", "text"),
    ), needs_member=True),
    ActionType("webhook", "Call a webhook", "POST to an external https webhook (Discord, Zapier, Make...).", (
        ActionField("url", "Webhook URL (https)", "text", True),
        ActionField("message", "Message", "textarea", description="Sent as content to Discord webhooks"),
        ActionField("payload", "JSON payload", "json", description="Optional; string values support variables"),
    )),
    ActionType("create_role", "Create a role", "Create a new role, optionally giving it to the member.", (
        ActionField("name", "Role name", "text", True, description="Supports variables"),
        ActionField("color", "Colour (hex)", "text", default="7C3AED"),
        ActionField("assign", "Give it to the member", "bool", default=False),
    )),
    ActionType("delay", "Wait", f"Pause before the next action (max {MAX_DELAY} s, {MAX_TOTAL_DELAY} s per run).", (
        ActionField("seconds", "Seconds", "number", True, 5),
    )),
    ActionType("trigger_automation", "Run another automation", "Run the actions of another custom automation.", (
        ActionField("hook_id", "Automation", "automation", True),
    )),
)}


def _num(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def summarize(action: dict[str, Any]) -> str:
    kind = ACTION_TYPES.get(str(action.get("type")))
    if kind is None:
        return f"Unknown action `{action.get('type')}`"
    detail = ""
    match kind.id:
        case "send_message":
            where = f"<#{action['channel_id']}>" if action.get("channel_id") else "event channel"
            detail = f"{where} · {cards.truncate(str(action.get('message', '')).replace(chr(10), ' '), 60)}"
        case "send_dm":
            detail = cards.truncate(str(action.get("message", "")).replace("\n", " "), 70)
        case "add_role" | "remove_role":
            detail = f"<@&{action['role_id']}>" if action.get("role_id") else ""
        case "timeout":
            detail = f"{int(_num(action.get('seconds'), 60))} s"
        case "webhook":
            detail = cards.truncate(urlsplit(str(action.get("url", ""))).hostname or "", 50)
        case "create_role":
            detail = cards.truncate(str(action.get("name", "")), 50)
        case "delay":
            detail = f"{int(_num(action.get('seconds'), 0))} s"
        case "trigger_automation":
            detail = f"`{action.get('hook_id', '')}`"
    return f"{kind.name}" + (f" · {detail}" if detail else "")


def action_problems(action: dict[str, Any]) -> list[str]:
    kind = ACTION_TYPES.get(str(action.get("type")))
    if kind is None:
        return [f"unknown action type {action.get('type')!r}"]
    problems = [f"{f.label} is required" for f in kind.fields
                if f.required and action.get(f.key) in (None, "", [])]
    if kind.id == "webhook" and action.get("url") and (err := check_url(str(action["url"]))):
        problems.append(err)
    if kind.id == "delay" and not 0 < _num(action.get("seconds")) <= MAX_DELAY:
        problems.append(f"seconds must be between 1 and {MAX_DELAY}")
    if kind.id == "timeout" and not 0 < _num(action.get("seconds")) <= MAX_TIMEOUT:
        problems.append("seconds must be between 1 and 2419200 (28 days)")
    return problems


def validate_actions(config: dict[str, Any]) -> list[str]:
    actions = config.get("actions") or []
    if not isinstance(actions, list):
        return ["actions must be a list"]
    errors = []
    if len(actions) > MAX_ACTIONS:
        errors.append(f"at most {MAX_ACTIONS} actions")
    for i, action in enumerate(actions, 1):
        errors += [f"action {i}: {p}" for p in action_problems(action if isinstance(action, dict) else {})]
    if config.get("trigger") == "message" and config.get("match") == "regex":
        try:
            re.compile(str(config.get("keyword") or ""))
        except re.error as exc:
            errors.append(f"keyword is not a valid regular expression ({exc})")
    if config.get("trigger") == "schedule":
        if _num(config.get("interval_minutes"), 0) < 1:
            errors.append("interval must be at least 1 minute")
        if any(isinstance(a, dict) and (t := ACTION_TYPES.get(str(a.get("type")))) and t.needs_member
               for a in actions):
            errors.append("scheduled automations have no member - remove role, DM and timeout actions")
    return errors


_last_tick: dict[str, float] = {}


def _message_matches(config: dict[str, Any], content: str) -> bool:
    mode = config.get("match") or "any"
    keyword = str(config.get("keyword") or "")
    if mode == "any" or not keyword:
        return True
    text, needle = content.lower(), keyword.lower()
    match mode:
        case "contains":
            return needle in text
        case "exact":
            return text.strip() == needle.strip()
        case "starts_with":
            return text.startswith(needle)
        case "regex":
            try:
                return re.search(keyword, content[:4000], re.IGNORECASE) is not None
            except re.error:
                return False
    return False


def accepts(auto: Automation, event: str, payload: dict[str, Any]) -> bool:
    c = auto.config
    trigger = c.get("trigger") or "message"
    if TRIGGERS.get(trigger, ("", ""))[1] != event:
        return False
    match trigger:
        case "message":
            message = payload.get("message")
            return message is not None and _message_matches(c, message.content or "")
        case "reaction_add":
            wanted = str(c.get("emoji") or "").strip()
            emoji = payload["payload"].emoji
            return not wanted or wanted in (str(emoji), emoji.name or "", str(emoji.id or ""))
        case "voice_join":
            before, after = payload["before"], payload["after"]
            if after.channel is None or before.channel == after.channel:
                return False
            only = c.get("voice_channel_id")
            return not only or str(after.channel.id) == str(only)
        case "schedule":
            interval = max(1.0, _num(c.get("interval_minutes"), 60)) * 60
            last = _last_tick.get(auto.hook_id)
            if last is None and auto.last_run:
                with contextlib.suppress(ValueError):
                    last = dt.datetime.fromisoformat(auto.last_run).timestamp()
            if last is not None and time.time() - last < interval:
                return False
            _last_tick[auto.hook_id] = time.time()
            return True
    return True


def build_context(bot: Any, guild_id: int, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    guild: discord.Guild | None = bot.get_guild(guild_id)
    member: discord.Member | None = None
    channel: Any = None
    values: dict[str, Any] = {}
    if (message := payload.get("message")) is not None:
        member = message.author if isinstance(message.author, discord.Member) else None
        channel = message.channel
        values["content"] = message.content
        values["message_link"] = message.jump_url
    elif (raw := payload.get("payload")) is not None:
        member = raw.member
        channel = bot.get_channel(raw.channel_id)
        values["emoji"] = str(raw.emoji)
    else:
        member = payload.get("member")
        if (after := payload.get("after")) is not None and after.channel is not None:
            channel = after.channel
            values["voice_channel"] = after.channel.name
    if member is not None:
        values.update(member_values(member, guild))
    elif guild is not None:
        values.update({"server": guild.name, "guild_name": guild.name, "member_count": guild.member_count})
    if channel is not None:
        values["channel"] = getattr(channel, "mention", "")
        values["channel_name"] = getattr(channel, "name", "")
    values["event"] = event
    return {"guild": guild, "member": member, "channel": channel, "values": values, "delay_total": 0.0}


def _render_json(value: Any, values: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return render(value, **values)
    if isinstance(value, list):
        return [_render_json(v, values) for v in value]
    if isinstance(value, dict):
        return {k: _render_json(v, values) for k, v in value.items()}
    return value


class ActionError(RuntimeError):
    pass


async def _do(rt: Runtime, auto: Automation, action: dict[str, Any], ctx: dict[str, Any], depth: int,
              chain: tuple[str, ...]) -> None:
    kind = ACTION_TYPES[action["type"]]
    guild: discord.Guild | None = ctx["guild"]
    member: discord.Member | None = ctx["member"]
    values = ctx["values"]
    if kind.needs_member and member is None:
        raise ActionError("this event has no member")
    if guild is None:
        raise ActionError("server not available")
    mentions = discord.AllowedMentions(everyone=False, roles=False, users=True)
    match kind.id:
        case "send_message":
            channel = rt.channel(action["channel_id"]) if action.get("channel_id") else ctx["channel"]
            if channel is None:
                raise ActionError("no channel to send to")
            await rt.send(channel, render(str(action.get("message", "")), **values), card=bool(action.get("card", True)),
                          title=render(str(action["title"]), **values) if action.get("title") else None,
                          accent=action.get("color"))
        case "send_dm":
            assert member is not None
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await member.send(cards.truncate(render(str(action.get("message", "")), **values), 2000),
                                  allowed_mentions=mentions)
        case "add_role" | "remove_role":
            assert member is not None
            role = guild.get_role(int(action["role_id"]))
            if role is None:
                raise ActionError("role no longer exists")
            if role >= guild.me.top_role or role.managed:
                raise ActionError(f"cannot manage {role.name} (above the bot's highest role or managed)")
            reason = f"Automation {auto.name}"
            if kind.id == "add_role" and role not in member.roles:
                await member.add_roles(role, reason=reason)
            elif kind.id == "remove_role" and role in member.roles:
                await member.remove_roles(role, reason=reason)
        case "timeout":
            assert member is not None
            seconds = min(max(_num(action.get("seconds"), 60), 1), MAX_TIMEOUT)
            await member.timeout(dt.timedelta(seconds=seconds),
                                 reason=render(str(action.get("reason") or f"Automation {auto.name}"), **values)[:500])
        case "webhook":
            url = str(action.get("url", ""))
            if err := check_url(url):
                raise ActionError(err)
            if not rt.throttle(f"wh:{auto.hook_id}", 1.0):
                raise ActionError("webhook rate limit (1 per second)")
            payload = action.get("payload")
            if isinstance(payload, str) and payload.strip():
                payload = json.loads(payload)
            text = render(str(action.get("message") or ""), **values)
            if payload:
                body = _render_json(payload, values)
            elif "/api/webhooks/" in url:
                body = {"content": cards.truncate(text or f"{auto.name} ran", 2000), "allowed_mentions": {"parse": []}}
            else:
                body = {"automation": auto.name, "event": values.get("event"), "server_id": guild.id,
                        "user_id": member.id if member else None, "message": text,
                        "timestamp": dt.datetime.now(dt.UTC).isoformat()}
            session = await rt.cog.http()
            async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status >= 400:
                    raise ActionError(f"webhook responded {resp.status}")
        case "create_role":
            if not rt.throttle(f"cr:{guild.id}", 10.0):
                raise ActionError("role creation is limited to one every 10 seconds per server")
            if len(guild.roles) >= 245:
                raise ActionError("the server is close to Discord's role limit")
            role = await guild.create_role(name=render(str(action.get("name", "new role")), **values)[:100],
                                           colour=_colour(action.get("color")) or discord.Colour.default(),
                                           reason=f"Automation {auto.name}")
            values["created_role"] = role.mention
            if action.get("assign") and member is not None:
                await member.add_roles(role, reason=f"Automation {auto.name}")
        case "delay":
            seconds = min(max(_num(action.get("seconds"), 1), 0), MAX_DELAY)
            if ctx["delay_total"] + seconds > MAX_TOTAL_DELAY:
                raise ActionError(f"total wait per run is limited to {MAX_TOTAL_DELAY} s")
            ctx["delay_total"] += seconds
            await asyncio.sleep(seconds)
        case "trigger_automation":
            target = rt.cog.find(str(action.get("hook_id", "")))
            if target is None or target.guild_id != auto.guild_id or target.template != CUSTOM.id:
                raise ActionError("target automation not found in this server")
            if target.hook_id in chain:
                raise ActionError("automation loop detected: " + " -> ".join((*chain, target.hook_id)))
            if depth + 1 >= MAX_DEPTH:
                raise ActionError(f"automations can chain at most {MAX_DEPTH} levels deep")
            if target.enabled:
                await run_actions(rt, target, target.config.get("actions") or [], ctx, depth=depth + 1,
                                  chain=(*chain, target.hook_id))


async def run_actions(rt: Runtime, auto: Automation, actions: list[dict[str, Any]], ctx: dict[str, Any], *,
                      depth: int = 0, chain: tuple[str, ...] | None = None) -> None:
    chain = chain or (auto.hook_id,)
    errors: list[str] = []
    for i, action in enumerate(actions[:MAX_ACTIONS], 1):
        if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
            errors.append(f"#{i}: unknown action")
            continue
        try:
            await _do(rt, auto, action, ctx, depth, chain)
        except (ActionError, discord.HTTPException, aiohttp.ClientError, TimeoutError,
                ValueError, TypeError, KeyError) as exc:
            if getattr(exc, "nested", False):
                errors.append(str(exc))
            else:
                errors.append(f"#{i} {ACTION_TYPES[action['type']].name}: {cards.truncate(exc, 150)}")
            if auto.config.get("stop_on_error"):
                break
    if errors:
        prefix = f"in {auto.name}: " if depth else ""
        error = ActionError(prefix + "; ".join(errors)[:900])
        error.nested = depth > 0  # type: ignore[attr-defined]
        raise error


def _handler(event: str):
    async def handle(rt: Runtime, auto: Automation, **payload: Any) -> None:
        ctx = build_context(rt.bot, auto.guild_id, event, payload)
        await run_actions(rt, auto, auto.config.get("actions") or [], ctx)

    return handle


CUSTOM = Template(
    "custom", "Custom automation",
    "Pick a trigger and chain up to 15 actions: messages, DMs, roles, timeouts, webhooks, waits and more.",
    (
        Param("trigger", "Trigger", "choice", True, "message", choices=tuple(TRIGGERS)),
        Param("match", "Message filter", "choice", False, "contains", choices=MATCH_MODES,
              show_if=("trigger", ("message",))),
        Param("keyword", "Keyword or pattern", "text", False, "",
              "Used with the message filter; regex is case-insensitive", show_if=("trigger", ("message",))),
        Param("emoji", "Only this emoji", "text", False, "", "Optional, e.g. a unicode emoji or custom emoji name",
              show_if=("trigger", ("reaction_add",))),
        Param("voice_channel_id", "Only this voice channel", "channel", channel_types=VOICE,
              show_if=("trigger", ("voice_join",))),
        Param("interval_minutes", "Every N minutes", "number", False, 60, show_if=("trigger", ("schedule",))),
        Param("actions", "Actions", "actions", True, None, f"Up to {MAX_ACTIONS} actions, run in order"),
        Param("stop_on_error", "Stop at the first failed action", "bool", False, False),
    ),
    {event: _handler(event) for _, event in TRIGGERS.values()},
    accepts=accepts, validate=validate_actions, timeout=MAX_TOTAL_DELAY + 120, background=True,
)
TEMPLATES[CUSTOM.id] = CUSTOM
