# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import re
from typing import Any

import discord
from discord import components as dc

__all__ = ["channel_brief", "serialize_components", "serialize_message", "user_brief"]

MAX_TEXT = 4000
_USER = re.compile(r"<@!?(\d{5,25})>")
_ROLE = re.compile(r"<@&(\d{5,25})>")
_CHANNEL = re.compile(r"<#(\d{5,25})>")
_SYSTEM_FREE = (discord.MessageType.default, discord.MessageType.reply, discord.MessageType.chat_input_command,
                discord.MessageType.context_menu_command)


def _colour(value: Any) -> int | None:
    number = getattr(value, "value", None)
    return number if isinstance(number, int) and number else None


def user_brief(user: Any) -> dict[str, Any]:
    avatar = getattr(user, "display_avatar", None)
    return {
        "id": str(user.id),
        "name": str(getattr(user, "display_name", None) or getattr(user, "name", "Unknown")),
        "avatar": avatar.replace(size=64).url if avatar is not None else None,
        "bot": bool(getattr(user, "bot", False)),
        "color": _colour(getattr(user, "colour", None)),
    }


def channel_brief(channel: Any) -> dict[str, Any]:
    guild = getattr(channel, "guild", None)
    recipient = getattr(channel, "recipient", None)
    name = getattr(channel, "name", None) or (f"@{recipient.display_name}" if recipient else "Direct message")
    return {"id": str(channel.id), "name": str(name), "guild": guild.name if guild else None,
            "guild_id": str(guild.id) if guild else None}


def _media(item: Any) -> str | None:
    media = getattr(item, "media", None)
    return getattr(media, "url", None)


def _component(node: Any) -> dict[str, Any]:
    match node:
        case dc.Container():
            return {"t": "container", "accent": _colour(node.accent_colour), "spoiler": bool(node.spoiler),
                    "items": serialize_components(node.children)}
        case dc.SectionComponent():
            return {"t": "section", "items": serialize_components(node.children),
                    "accessory": _component(node.accessory) if node.accessory is not None else None}
        case dc.TextDisplay():
            return {"t": "text", "content": str(node.content)[:MAX_TEXT]}
        case dc.ThumbnailComponent():
            return {"t": "thumb", "url": _media(node), "alt": node.description}
        case dc.MediaGalleryComponent():
            return {"t": "gallery", "items": [{"url": _media(i), "alt": i.description} for i in node.items[:10]]}
        case dc.FileComponent():
            return {"t": "file", "url": _media(node), "name": node.name, "size": node.size}
        case dc.SeparatorComponent():
            return {"t": "sep", "visible": bool(node.visible)}
        case dc.ActionRow():
            return {"t": "row", "items": serialize_components(node.children)}
        case dc.Button():
            return {"t": "button", "label": node.label, "style": node.style.name, "url": node.url,
                    "disabled": bool(node.disabled), "emoji": str(node.emoji) if node.emoji else None}
        case dc.SelectMenu():
            return {"t": "select", "placeholder": node.placeholder, "disabled": bool(node.disabled),
                    "options": [str(o.label) for o in node.options[:25]]}
        case _:
            return {"t": "unknown", "kind": type(node).__name__}


def serialize_components(nodes: Any) -> list[dict[str, Any]]:
    return [_component(n) for n in list(nodes or [])[:40]]


def _embed(embed: discord.Embed) -> dict[str, Any]:
    def proxy(part: Any) -> str | None:
        return (getattr(part, "proxy_url", None) or getattr(part, "url", None)) if part else None

    return {
        "title": embed.title, "description": (embed.description or "")[:MAX_TEXT] or None, "url": embed.url,
        "color": _colour(embed.colour),
        "author": {"name": embed.author.name, "icon": getattr(embed.author, "proxy_icon_url", None)} if embed.author and embed.author.name else None,
        "footer": embed.footer.text if embed.footer and embed.footer.text else None,
        "image": proxy(embed.image), "thumbnail": proxy(embed.thumbnail),
        "fields": [{"name": f.name, "value": (f.value or "")[:1024], "inline": bool(f.inline)} for f in embed.fields[:25]],
        "at": embed.timestamp.timestamp() if embed.timestamp else None,
    }


def _texts(nodes: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for node in nodes:
        if node.get("t") == "text":
            out.append(node["content"])
        out.extend(_texts(node.get("items") or []))
    return out


def _mentions(message: discord.Message, texts: list[str]) -> dict[str, dict[str, Any]]:
    guild = message.guild
    users: dict[str, str] = {str(u.id): str(getattr(u, "display_name", u.name)) for u in message.mentions}
    roles: dict[str, dict[str, Any]] = {str(r.id): {"name": r.name, "color": _colour(r.colour)} for r in message.role_mentions}
    channels: dict[str, str] = {str(c.id): str(getattr(c, "name", "channel")) for c in message.channel_mentions}
    blob = "\n".join(texts)[:20000]
    state = message._state
    for raw in set(_USER.findall(blob)) - set(users):
        found = (guild.get_member(int(raw)) if guild else None) or state.get_user(int(raw))
        if found is not None:
            users[raw] = str(getattr(found, "display_name", found.name))
    if guild is not None:
        for raw in set(_ROLE.findall(blob)) - set(roles):
            role = guild.get_role(int(raw))
            if role is not None:
                roles[raw] = {"name": role.name, "color": _colour(role.colour)}
        for raw in set(_CHANNEL.findall(blob)) - set(channels):
            channel = guild.get_channel_or_thread(int(raw))
            if channel is not None:
                channels[raw] = channel.name
    return {"users": users, "roles": roles, "channels": channels}


def serialize_message(message: discord.Message, me_id: int | None = None) -> dict[str, Any]:
    components = serialize_components(message.components)
    embeds = [_embed(e) for e in message.embeds[:10]]
    content = (message.content or "")[:MAX_TEXT]
    system = None
    if message.type not in _SYSTEM_FREE:
        system = (message.system_content or "")[:500] or message.type.name.replace("_", " ")
    reply = None
    ref = message.reference
    if ref is not None and ref.message_id:
        target = ref.resolved if isinstance(ref.resolved, discord.Message) else None
        reply = {"id": str(ref.message_id),
                 "author": user_brief(target.author)["name"] if target else None,
                 "excerpt": (target.content or "")[:140] if target else None}
    texts = [content, *(e["description"] or "" for e in embeds), *_texts(components)]
    reactions = []
    for r in message.reactions[:30]:
        emoji = r.emoji
        reactions.append({"emoji": str(emoji), "id": str(emoji.id) if getattr(emoji, "id", None) else None,
                          "name": getattr(emoji, "name", str(emoji)), "animated": bool(getattr(emoji, "animated", False)),
                          "count": r.count, "me": bool(r.me)})
    return {
        "id": str(message.id),
        "channel_id": str(message.channel.id),
        "author": user_brief(message.author),
        "own": me_id is not None and message.author.id == me_id,
        "content": content,
        "system": system,
        "at": message.created_at.timestamp(),
        "edited_at": message.edited_at.timestamp() if message.edited_at else None,
        "pinned": bool(message.pinned),
        "card": bool(components) and not content,
        "reply": reply,
        "attachments": [{"url": a.url, "name": a.filename, "size": a.size, "type": a.content_type, "w": a.width,
                         "h": a.height, "spoiler": a.is_spoiler()} for a in message.attachments[:10]],
        "embeds": embeds,
        "components": components,
        "reactions": reactions,
        "stickers": [{"name": s.name, "url": s.url} for s in message.stickers[:3]],
        "mentions": _mentions(message, texts),
        "url": message.jump_url,
    }
