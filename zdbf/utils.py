# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import datetime as dt

__all__ = ["human_bytes", "human_duration", "parse_duration", "plural", "utcnow"]


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def plural(n: int, word: str, suffix: str = "s") -> str:
    return f"{n:,} {word}{'' if n == 1 else suffix}"


def human_duration(seconds: float, *, parts: int = 3) -> str:
    seconds = int(max(0, seconds))
    units = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
    out = []
    for suffix, size in units:
        value, seconds = divmod(seconds, size)
        if value:
            out.append(f"{value}{suffix}")
    return " ".join(out[:parts]) or "0s"


def human_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def parse_duration(text: str) -> int | None:
    import re

    text = text.strip().lower()
    if text.isdigit():
        return int(text)
    total = 0
    matched = False
    for value, unit in re.findall(r"(\d+)\s*([smhdw])", text):
        matched = True
        total += int(value) * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    return total if matched else None
