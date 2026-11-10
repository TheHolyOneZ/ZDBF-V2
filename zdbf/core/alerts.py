# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal

import discord

if TYPE_CHECKING:
    from .bot import ZDBFBot

log = logging.getLogger("zdbf.alerts")

Level = Literal["info", "success", "warning", "error", "critical"]
__all__ = ["AlertManager", "Level"]


class AlertManager:
    KV_KEY = "alerts.channels"

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.channels: dict[str, int] = {}
        self._last_sent: dict[tuple[str, str], float] = {}
        self.rate_limit_seconds = 30

    async def load(self) -> None:
        self.channels = {k: int(v) for k, v in (await self.bot.db.kv_get(self.KV_KEY, {})).items()}

    async def set_channel(self, system: str, channel_id: int | None) -> None:
        if channel_id is None:
            self.channels.pop(system, None)
        else:
            self.channels[system] = channel_id
        await self.bot.db.kv_set(self.KV_KEY, self.channels)

    def channel_for(self, system: str) -> int | None:
        return self.channels.get(system) or self.channels.get("default")

    async def send(self, system: str, message: str, level: Level = "warning", *, title: str | None = None) -> bool:
        log_level = {"info": logging.INFO, "success": logging.INFO, "warning": logging.WARNING}.get(level, logging.ERROR)
        log.log(log_level, "[%s] %s", system, message)

        key = (system, message)
        now = time.monotonic()
        last = self._last_sent.get(key)
        if last is not None and now - last < self.rate_limit_seconds:
            return False
        self._last_sent[key] = now
        if len(self._last_sent) > 500:
            self._last_sent = {k: v for k, v in self._last_sent.items() if now - v < self.rate_limit_seconds}

        channel_id = self.channel_for(system)
        if not channel_id:
            return False
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return False

        from ..ui import cards

        view = cards.alert_view(system, message, level, title=title)
        try:
            await channel.send(view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.warning("could not deliver alert to %s: %s", channel_id, exc)
            return False
        return True
