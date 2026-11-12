# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

__all__ = ["CommandError", "MetricsCollector"]


@dataclass(slots=True)
class CommandError:
    command: str
    error: str
    user_id: int
    guild_id: int | None
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    def __init__(self, recent: int = 100, window_seconds: int = 3600) -> None:
        self.started_at = time.time()
        self._monotonic_start = time.monotonic()
        self.commands_total = 0
        self.errors_total = 0
        self.rejections_total = 0
        self.rejection_reasons: Counter[str] = Counter()
        self.messages_seen = 0
        self.interactions_total = 0
        self.command_counter: Counter[str] = Counter()
        self.recent_commands: deque[tuple[str, float]] = deque(maxlen=recent)
        self.recent_errors: deque[CommandError] = deque(maxlen=recent)
        self.window_seconds = window_seconds

    @property
    def uptime(self) -> float:
        return time.monotonic() - self._monotonic_start

    def record_command(self, name: str) -> None:
        self.commands_total += 1
        self.command_counter[name] += 1
        self.recent_commands.append((name, time.time()))

    def record_error(self, command: str = "unknown", error: str = "", user_id: int = 0,
                     guild_id: int | None = None) -> None:
        self.errors_total += 1
        self.recent_errors.append(CommandError(command, error[:500], user_id, guild_id))

    def record_rejection(self, reason: str) -> None:
        self.rejections_total += 1
        self.rejection_reasons[reason] += 1

    def record_message(self) -> None:
        self.messages_seen += 1

    def record_interaction(self) -> None:
        self.interactions_total += 1

    def window_counts(self) -> tuple[int, int]:
        cutoff = time.time() - self.window_seconds
        cmds = sum(1 for _, ts in self.recent_commands if ts >= cutoff)
        errs = sum(1 for e in self.recent_errors if e.timestamp >= cutoff)
        return errs, cmds

    def error_rate(self) -> float:
        errs, cmds = self.window_counts()
        return round(errs / cmds * 100, 2) if cmds else 0.0

    def get_uptime(self) -> float:
        return self.uptime

    def get_stats(self) -> dict[str, Any]:
        return {
            "uptime": self.uptime,
            "commands_processed": self.commands_total,
            "errors": self.errors_total,
            "rejections": self.rejections_total,
            "messages_seen": self.messages_seen,
            "interactions": self.interactions_total,
            "error_rate": self.error_rate(),
            "top_commands": self.command_counter.most_common(10),
        }
