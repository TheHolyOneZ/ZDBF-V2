# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import discord

__all__ = ["Colors", "Emoji", "Glyph", "Status", "accent_for", "emoji_for", "status_dot"]


class Colors:
    PRIMARY = discord.Colour(0x5B6EF5)
    BRAND = discord.Colour(0x7C5CFF)
    SUCCESS = discord.Colour(0x2EA043)
    WARNING = discord.Colour(0xD29922)
    DANGER = discord.Colour(0xDA3633)
    INFO = discord.Colour(0x2F81F7)
    GOLD = discord.Colour(0xC9A227)
    MUTED = discord.Colour(0x3D444D)


class Status:
    OK = "🟢"
    WARN = "🟡"
    ERROR = "🔴"
    OFF = "⚪"


class Glyph:
    FIRST = "«"
    PREV = "‹"
    NEXT = "›"
    LAST = "»"
    BULLET = "•"
    DOT = "·"
    ARROW = "→"
    DASH = "—"


class Emoji:
    OK = Status.OK
    ERROR = Status.ERROR
    WARN = Status.WARN
    ONLINE = Status.OK
    IDLE = Status.WARN
    OFFLINE = Status.ERROR
    INFO = LOCK = CROWN = GEAR = CLOCK = CHART = PLUG = HOOK = BOX = SHARD = DB = BACKUP = ""
    CALENDAR = SHOP = BOOK = HEART = REFRESH = TRASH = BACK = ""
    FIRST, PREV, NEXT, LAST = Glyph.FIRST, Glyph.PREV, Glyph.NEXT, Glyph.LAST


_LEVEL_ACCENT = {
    "info": Colors.INFO,
    "success": Colors.SUCCESS,
    "warning": Colors.WARNING,
    "error": Colors.DANGER,
    "danger": Colors.DANGER,
    "critical": Colors.DANGER,
    "primary": Colors.PRIMARY,
    "brand": Colors.BRAND,
    "gold": Colors.GOLD,
    "muted": Colors.MUTED,
}

_LEVEL_DOT = {
    "success": Status.OK,
    "info": Status.OK,
    "warning": Status.WARN,
    "error": Status.ERROR,
    "critical": Status.ERROR,
}


def accent_for(level: str) -> discord.Colour:
    return _LEVEL_ACCENT.get(level, Colors.PRIMARY)


def status_dot(ok: bool | None) -> str:
    return Status.OK if ok else Status.WARN if ok is None else Status.ERROR


def emoji_for(level: str) -> str:
    return _LEVEL_DOT.get(level, "")
