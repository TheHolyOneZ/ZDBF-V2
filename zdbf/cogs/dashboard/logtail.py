# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

__all__ = ["TOPIC", "LogTail", "parse_lines", "redactor"]

TOPIC = "logs.tail"
BUFFER = 1000
RATE = 60
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_TOKEN = re.compile(r"[MNO][A-Za-z\d_-]{23,28}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,40}")
_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3}) \| (\w+)\s* \| ([^|]+?) \| (.*)$")
_formatter = logging.Formatter()


def redactor(secrets: Iterable[str]) -> Callable[[str], str]:
    words = sorted({s for s in secrets if isinstance(s, str) and len(s) >= 8}, key=len, reverse=True)

    def clean(text: str) -> str:
        for word in words:
            if word in text:
                text = text.replace(word, "[hidden]")
        return _TOKEN.sub("[hidden token]", text)

    return clean


def _entry(t: float, level: str, name: str, message: str, exc: str | None, clean: Callable[[str], str]) -> dict[str, Any]:
    out: dict[str, Any] = {"t": round(t, 3), "level": level, "name": name[:120], "msg": clean(message)[:4000]}
    if exc:
        out["exc"] = clean(exc)[-6000:]
    return out


def parse_lines(lines: list[str], clean: Callable[[str], str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in lines:
        match = _LINE.match(line)
        if match:
            stamp, millis, level, name, message = match.groups()
            try:
                t = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S")) + int(millis) / 1000
            except ValueError:
                continue
            out.append(_entry(t, level.upper(), name.strip(), message, None, clean))
        elif out and line.strip():
            entry = out[-1]
            extra = clean(line)
            entry["exc"] = ((entry.get("exc") + "\n") if entry.get("exc") else "") + extra
            if len(entry["exc"]) > 6000:
                entry["exc"] = entry["exc"][-6000:]
    return out


class LogTail(logging.Handler):
    def __init__(self, publish: Callable[[dict[str, Any]], None], clean: Callable[[str], str],
                 level: int = logging.INFO) -> None:
        super().__init__(level)
        self.publish = publish
        self.clean = clean
        self.buffer: deque[dict[str, Any]] = deque(maxlen=BUFFER)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.dropped = 0
        self._window = (0.0, 0)
        self._local = threading.local()

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        logging.getLogger().addHandler(self)

    def detach(self) -> None:
        logging.getLogger().removeHandler(self)
        self.loop = None

    def _allowed(self, now: float) -> bool:
        second, count = self._window
        if int(now) != second:
            self._window = (int(now), 1)
            return True
        if count >= RATE:
            self.dropped += 1
            return False
        self._window = (second, count + 1)
        return True

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._local, "busy", False):
            return
        self._local.busy = True
        try:
            exc = _formatter.formatException(record.exc_info) if record.exc_info else None
            entry = _entry(record.created, record.levelname, record.name, record.getMessage(), exc, self.clean)
            self.buffer.append(entry)
            loop = self.loop
            if loop is None or loop.is_closed() or not self._allowed(record.created):
                return
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                self.publish(entry)
            else:
                loop.call_soon_threadsafe(self.publish, entry)
        except Exception:
            self.handleError(record)
        finally:
            self._local.busy = False


def read_tail(path: Path, max_bytes: int) -> list[str]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    with path.open("rb") as fh:
        start = max(0, size - max_bytes)
        fh.seek(start)
        data = fh.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    return lines
