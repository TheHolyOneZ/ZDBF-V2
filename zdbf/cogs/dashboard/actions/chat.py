# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import base64
import binascii
import functools
import io
import re
from collections.abc import Awaitable, Callable
from typing import Any

import discord

from ..messages import channel_brief, serialize_message
from . import ActionContext, ActionError, action

HISTORY_MAX = 50
FILES_MAX = 3
FILES_BYTES = 3 * 1024 * 1024
_CUSTOM_EMOJI = re.compile(r"^<?(a?):?([A-Za-z0-9_]{2,32}):(\d{5,25})>?$")
_FILENAME = re.compile(r"[^A-Za-z0-9._ -]")
_KINDS = {
    discord.ChannelType.text: "text", discord.ChannelType.news: "news", discord.ChannelType.voice: "voice",
    discord.ChannelType.stage_voice: "stage", discord.ChannelType.forum: "forum", discord.ChannelType.media: "forum",
}
Handler = Callable[[ActionContext], Awaitable[Any]]


def discord_errors(handler: Handler) -> Handler:
    @functools.wraps(handler)
    async def wrapper(ctx: ActionContext) -> Any:
        try:
            return await handler(ctx)
        except discord.Forbidden as exc:
            raise ActionError("The bot is missing a permission for that in this channel.") from exc
        except discord.NotFound as exc:
            raise ActionError("That message or channel no longer exists.") from exc
        except discord.HTTPException as exc:
            raise ActionError(f"Discord refused the request ({exc.status}): {str(exc.text)[:200]}") from exc

    return wrapper


def permissions(channel: Any) -> discord.Permissions:
    guild = getattr(channel, "guild", None)
    if guild is None:
        return discord.Permissions(view_channel=True, read_message_history=True, send_messages=True,
                                   add_reactions=True, attach_files=True, embed_links=True)
    return channel.permissions_for(guild.me)


def can(channel: Any) -> dict[str, bool]:
    p = permissions(channel)
    thread = isinstance(channel, discord.Thread)
    locked = thread and (channel.locked or channel.archived) and not p.manage_threads
    send = (p.send_messages_in_threads if thread else p.send_messages) and not locked
    return {
        "read": bool(p.view_channel and p.read_message_history),
        "send": bool(p.view_channel and send),
        "attach": bool(send and p.attach_files),
        "react": bool(p.view_channel and p.read_message_history and p.add_reactions),
        "manage": bool(p.manage_messages),
    }


def resolve_channel(ctx: ActionContext, need: str = "read") -> Any:
    channel = ctx.bot.get_channel(ctx.integer("channel_id", minimum=1))
    if channel is None or not isinstance(channel, discord.abc.Messageable):
        raise ActionError("That channel no longer exists or the bot cannot see it.")
    if not can(channel)[need]:
        words = {"read": "read", "send": "send messages in", "attach": "attach files in", "react": "react in",
                 "manage": "manage messages in"}
        raise ActionError(f"The bot is not allowed to {words[need]} that channel.")
    return channel


def _message(ctx: ActionContext, channel: Any) -> discord.PartialMessage:
    return channel.get_partial_message(ctx.integer("message_id", minimum=1))


def build_tree(bot: Any) -> dict[str, Any]:
    guilds = []
    for guild in sorted(bot.guilds, key=lambda g: g.name.lower())[:200]:
        channels = []
        for channel in guild.channels:
            kind = _KINDS.get(channel.type)
            if kind is None:
                continue
            allowed = can(channel)
            if not permissions(channel).view_channel:
                continue
            category = channel.category
            channels.append({
                "id": str(channel.id), "name": channel.name, "kind": kind,
                "category": category.name if category else None,
                "order": [category.position if category else -1, 1 if kind in ("voice", "stage") else 0, channel.position],
                "read": allowed["read"] and kind != "forum", "send": allowed["send"] and kind != "forum",
                "nsfw": bool(getattr(channel, "nsfw", False)),
            })
        channels.sort(key=lambda c: c["order"])
        threads = [
            {"id": str(t.id), "name": t.name, "parent": str(t.parent_id), "read": can(t)["read"], "send": can(t)["send"],
             "archived": bool(t.archived)}
            for t in guild.threads if permissions(t).view_channel
        ]
        guilds.append({"id": str(guild.id), "name": guild.name,
                       "icon": guild.icon.replace(size=64).url if guild.icon else None,
                       "channels": channels[:500], "threads": threads[:300]})
    dms = [
        {"id": str(c.id), "name": c.recipient.display_name, "avatar": c.recipient.display_avatar.replace(size=64).url}
        for c in bot.private_channels if isinstance(c, discord.DMChannel) and c.recipient is not None
    ]
    return {"guilds": guilds, "dms": dms[:100]}


@action("chat.tree", "chat.read", timeout=30)
async def tree(ctx: ActionContext) -> dict[str, Any]:
    return build_tree(ctx.bot)


@action("chat.history", "chat.read", timeout=30)
@discord_errors
async def history(ctx: ActionContext) -> dict[str, Any]:
    channel = resolve_channel(ctx, "read")
    limit = ctx.integer("limit", default=40, minimum=1, maximum=HISTORY_MAX)
    before = ctx.integer("before", default=0, minimum=0)
    found = [m async for m in channel.history(limit=limit, before=discord.Object(before) if before else None)]
    me = ctx.bot.user.id if ctx.bot.user else None
    return {
        "channel": {**channel_brief(channel), "topic": getattr(channel, "topic", None), "can": can(channel)},
        "messages": [serialize_message(m, me) for m in reversed(found)],
        "more": len(found) == limit,
    }


def _files(ctx: ActionContext) -> list[discord.File]:
    raw = ctx.args.get("files")
    if not raw:
        return []
    if not isinstance(raw, list) or len(raw) > FILES_MAX:
        raise ActionError(f"Attach at most {FILES_MAX} files.")
    out, total = [], 0
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("data"), str):
            raise ActionError("An attachment could not be read.")
        try:
            data = base64.b64decode(item["data"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ActionError("An attachment could not be read.") from exc
        total += len(data)
        if total > FILES_BYTES:
            raise ActionError(f"Attachments are limited to {FILES_BYTES // (1024 * 1024)} MB per message for now.")
        name = _FILENAME.sub("_", str(item.get("name") or "file"))[-80:].strip(". ") or "file"
        out.append(discord.File(io.BytesIO(data), filename=name))
    return out


@action("chat.send", "chat.send", timeout=60,
        summary=lambda a: f"send a message to channel {a.get('channel_id')}")
@discord_errors
async def send(ctx: ActionContext) -> dict[str, Any]:
    files = _files(ctx)
    channel = resolve_channel(ctx, "attach" if files else "send")
    content = ctx.text("content", default="", max_length=2000).strip()
    if not content and not files:
        raise ActionError("Write a message or attach a file.")
    reference = None
    reply_to = ctx.integer("reply_to", default=0, minimum=0)
    if reply_to:
        reference = discord.MessageReference(message_id=reply_to, channel_id=channel.id, fail_if_not_exists=False)
    message = await channel.send(content or None, files=files, reference=reference, mention_author=False)
    return {"message": serialize_message(message, ctx.bot.user.id if ctx.bot.user else None)}


@action("chat.edit", "chat.send", timeout=30)
@discord_errors
async def edit(ctx: ActionContext) -> dict[str, Any]:
    channel = resolve_channel(ctx, "read")
    content = ctx.text("content", max_length=2000).strip()
    message = await _message(ctx, channel).fetch()
    if ctx.bot.user is None or message.author.id != ctx.bot.user.id:
        raise ActionError("Only the bot's own messages can be edited.")
    if message.components and not message.content:
        raise ActionError("Card messages cannot be edited as text.")
    edited = await message.edit(content=content)
    return {"message": serialize_message(edited, ctx.bot.user.id)}


async def _delete(ctx: ActionContext, *, own_only: bool) -> dict[str, Any]:
    channel = resolve_channel(ctx, "read")
    partial = _message(ctx, channel)
    if own_only:
        message = await partial.fetch()
        if ctx.bot.user is None or message.author.id != ctx.bot.user.id:
            raise ActionError("That message is not from the bot. Deleting it needs the capability `chat.moderate`.")
    elif not can(channel)["manage"]:
        raise ActionError("The bot is not allowed to manage messages in that channel.")
    await partial.delete()
    return {"deleted": str(partial.id)}


@action("chat.delete", "chat.send", timeout=30)
@discord_errors
async def delete_own(ctx: ActionContext) -> dict[str, Any]:
    return await _delete(ctx, own_only=True)


@action("chat.delete_any", "chat.moderate", timeout=30,
        summary=lambda a: f"delete message {a.get('message_id')} in channel {a.get('channel_id')}")
@discord_errors
async def delete_any(ctx: ActionContext) -> dict[str, Any]:
    return await _delete(ctx, own_only=False)


def parse_emoji(raw: str) -> str | discord.PartialEmoji:
    raw = raw.strip()
    match = _CUSTOM_EMOJI.match(raw)
    if match:
        return discord.PartialEmoji(name=match.group(2), id=int(match.group(3)), animated=bool(match.group(1)))
    if not raw or len(raw) > 32 or raw.isascii():
        raise ActionError("That is not an emoji.")
    return raw


@action("chat.react", "chat.send", timeout=30)
@discord_errors
async def react(ctx: ActionContext) -> dict[str, Any]:
    channel = resolve_channel(ctx, "read")
    emoji = parse_emoji(ctx.text("emoji", max_length=80))
    partial = _message(ctx, channel)
    if ctx.flag("remove"):
        await partial.remove_reaction(emoji, ctx.bot.user)
    else:
        await partial.add_reaction(emoji)
    return {"ok": True}


@action("chat.pin", "chat.moderate", timeout=30)
@discord_errors
async def pin(ctx: ActionContext) -> dict[str, Any]:
    channel = resolve_channel(ctx, "manage")
    partial = _message(ctx, channel)
    if ctx.flag("unpin"):
        await partial.unpin()
    else:
        await partial.pin()
    return {"pinned": not ctx.flag("unpin")}
