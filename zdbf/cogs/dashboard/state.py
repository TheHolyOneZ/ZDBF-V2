# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any

import discord
import psutil

from ...core.extensions import BUILTIN_MODULES
from .actions import catalogue
from .panels import panels

if TYPE_CHECKING:
    from .cog import Dashboard

__all__ = ["ALWAYS", "StateHub"]

ALWAYS = frozenset({"meta", "overview", "activity"})
SERIES_POINTS = 180
RATE_WINDOW = 60.0
RATE_SAMPLES = 13
GUILD_LIMIT = 250
Collector = Callable[[], Awaitable[Any]]


def _ms(seconds: float) -> float | None:
    return None if seconds is None or math.isnan(seconds) or math.isinf(seconds) else round(seconds * 1000, 1)


class StateHub:
    def __init__(self, cog: Dashboard) -> None:
        self.cog = cog
        self.bot = cog.bot
        self.process = psutil.Process(os.getpid())
        self.process.cpu_percent(None)
        self.series: deque[list[float | None]] = deque(maxlen=SERIES_POINTS)
        self._hashes: dict[str, str] = {}
        self._totals: deque[tuple[float, int]] = deque(maxlen=RATE_SAMPLES)
        self.collectors: dict[str, Collector] = {
            "meta": self.meta,
            "overview": self.overview,
            "series": self.series_topic,
            "activity": self.activity,
            "guilds": self.guilds,
        }

    def reset(self) -> None:
        self._hashes.clear()

    def register(self, topic: str, collector: Collector) -> None:
        self.collectors[topic] = collector

    def unregister(self, topic: str) -> None:
        self.collectors.pop(topic, None)
        self._hashes.pop(topic, None)

    async def changed(self, topics: Iterable[str], *, force: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for topic in sorted(set(topics)):
            collector = self.collectors.get(topic)
            if collector is None:
                continue
            data = await collector()
            digest = hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
            if force or self._hashes.get(topic) != digest:
                self._hashes[topic] = digest
                out[topic] = data
        return out

    def _lag(self) -> float | None:
        diag = self.bot.get_cog("Diagnostics")
        value = getattr(diag, "loop_lag_ms", None)
        return round(float(value), 2) if isinstance(value, int | float) else None

    def sample(self) -> None:
        now = time.time()
        total = self.bot.metrics.commands_total
        self._totals.append((now, total))
        since, before = self._totals[0]
        rate = round((total - before) / max(now - since, RATE_WINDOW) * 60, 2)
        with self.process.oneshot():
            cpu = round(self.process.cpu_percent(None), 1)
            rss = self.process.memory_info().rss
        self.series.append([round(now, 1), cpu, round(rss / 1048576, 1), _ms(self.bot.latency), self._lag(), rate])

    async def meta(self) -> dict[str, Any]:
        bot = self.bot
        user = bot.user
        link = self.cog.link
        return {
            "bot": {
                "id": str(user.id) if user else None,
                "name": user.display_name if user else None,
                "tag": str(user) if user else None,
                "avatar": user.display_avatar.replace(size=128).url if user else None,
            },
            "version": bot.version,
            "discord_py": discord.__version__,
            "python": platform.python_version(),
            "platform": platform.system(),
            "prefix": bot.config.settings.bot.prefix,
            "owners": [str(i) for i in sorted(bot.owner_id_set)],
            "capabilities": self.cog.policy.describe(),
            "locked": self.cog.policy.locked,
            "actions": catalogue(),
            "modules": [k for k, mod in BUILTIN_MODULES.items() if mod in bot.extensions],
            "file_roots": list(self.cog.settings.file_roots),
            "panels": panels.describe(),
            "paired_at": link.paired_at if link else None,
        }

    async def overview(self) -> dict[str, Any]:
        bot = self.bot
        metrics = bot.metrics
        with self.process.oneshot():
            rss = self.process.memory_info().rss
            threads = self.process.num_threads()
        memory = psutil.virtual_memory()
        try:
            disk = shutil.disk_usage(".")
            disk_info: dict[str, int] | None = {"used": disk.used, "total": disk.total, "free": disk.free}
        except OSError:
            disk_info = None
        shard_guilds: dict[int, int] = {}
        for guild in bot.guilds:
            shard_guilds[guild.shard_id] = shard_guilds.get(guild.shard_id, 0) + 1
        shards = [
            {"id": sid, "latency_ms": _ms(shard.latency), "guilds": shard_guilds.get(sid, 0), "closed": shard.is_closed()}
            for sid, shard in sorted(bot.shards.items())
        ]
        loaded = [m for m in bot.extensions if not m.startswith("zdbf.")]
        return {
            "ready": bot.is_ready(),
            "latency_ms": _ms(bot.latency),
            "uptime": round(metrics.uptime),
            "started_at": round(bot.started_at),
            "guilds": len(bot.guilds),
            "members": sum(g.member_count or 0 for g in bot.guilds),
            "shards": shards,
            "commands": {
                "total": metrics.commands_total,
                "errors": metrics.errors_total,
                "error_rate": metrics.error_rate(),
                "messages": metrics.messages_seen,
                "interactions": metrics.interactions_total,
                "registered": sum(1 for _ in bot.walk_commands()),
                "slash": bot.slash_command_count(),
                "top": [[name, count] for name, count in metrics.command_counter.most_common(8)],
            },
            "extensions": {"loaded": len(loaded), "modules": len(bot.extensions) - len(loaded),
                           "failed": len(bot.ext.failed)},
            "process": {
                "cpu": self.series[-1][1] if self.series else 0.0,
                "rss": rss,
                "threads": threads,
                "pid": self.process.pid,
                "system_memory": memory.percent,
                "system_memory_total": memory.total,
                "cpu_count": psutil.cpu_count() or 1,
            },
            "disk": disk_info,
            "loop_lag_ms": self._lag(),
            "loop_lag_threshold_ms": bot.config.settings.diagnostics.loop_lag_threshold_ms,
            "hooks": {"queue": bot.hooks.queue_size, "running": bot.hooks.running},
            "database": {"queries": bot.db.query_count, "retries": bot.db.retries},
            "approvals_pending": self.cog.approvals.pending,
        }

    async def series_topic(self) -> dict[str, Any]:
        return {"fields": ["t", "cpu", "rss_mb", "latency_ms", "lag_ms", "commands_per_min"],
                "points": list(self.series)}

    async def activity(self) -> dict[str, Any]:
        metrics = self.bot.metrics
        return {
            "commands": [{"name": name, "at": round(at, 1)} for name, at in list(metrics.recent_commands)[-25:][::-1]],
            "errors": [
                {"command": e.command, "error": e.error[:300], "user_id": str(e.user_id),
                 "guild_id": str(e.guild_id) if e.guild_id else None, "at": round(e.timestamp, 1)}
                for e in list(metrics.recent_errors)[-25:][::-1]
            ],
            "alerts": [
                {"system": a["system"], "message": str(a["message"])[:400], "level": a["level"],
                 "title": a.get("title"), "at": round(a["at"], 1)}
                for a in list(self.bot.alerts.recent)[-25:][::-1]
            ],
        }

    async def guilds(self) -> dict[str, Any]:
        ordered = sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        return {
            "total": len(ordered),
            "items": [
                {
                    "id": str(g.id),
                    "name": g.name,
                    "icon": g.icon.replace(size=64).url if g.icon else None,
                    "members": g.member_count or 0,
                    "owner_id": str(g.owner_id) if g.owner_id else None,
                    "shard": g.shard_id,
                    "joined_at": round(g.me.joined_at.timestamp()) if g.me and g.me.joined_at else None,
                }
                for g in ordered[:GUILD_LIMIT]
            ],
        }
