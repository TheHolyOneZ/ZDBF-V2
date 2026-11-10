# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("zdbf.storage")

__all__ = ["AtomicFileHandler", "global_file_handler", "write_bytes_durable"]


@dataclass
class _LockEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.monotonic)


class AtomicFileHandler:
    def __init__(self, cache_ttl: float = 300, max_cache_size: int = 1000, retries: int = 3) -> None:
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._locks: dict[str, _LockEntry] = {}
        self.cache_ttl = cache_ttl
        self.max_cache_size = max_cache_size
        self.retries = retries
        self.metrics: dict[str, int] = dict.fromkeys(
            (
                "reads",
                "writes",
                "cache_hits",
                "cache_misses",
                "cache_bypasses",
                "write_failures",
                "read_failures",
                "lock_cleanups",
                "cache_invalidations",
            ),
            0,
        )

    @staticmethod
    def _key(path: str | os.PathLike[str]) -> str:
        return str(Path(path).resolve())

    def _lock(self, key: str) -> asyncio.Lock:
        entry = self._locks.get(key)
        if entry is None:
            entry = self._locks[key] = _LockEntry()
            if len(self._locks) > 500:
                self._cleanup_locks()
        entry.last_used = time.monotonic()
        return entry.lock

    def _cleanup_locks(self, idle: float = 300) -> int:
        now = time.monotonic()
        stale = [k for k, e in self._locks.items() if not e.lock.locked() and now - e.last_used > idle]
        for k in stale:
            del self._locks[k]
        self.metrics["lock_cleanups"] += 1
        return len(stale)

    def _cache_get(self, key: str) -> Any | None:
        hit = self._cache.get(key)
        if hit is not None and time.monotonic() - hit[1] < self.cache_ttl:
            self._cache.move_to_end(key)
            self.metrics["cache_hits"] += 1
            return hit[0]
        if hit is not None:
            del self._cache[key]
        self.metrics["cache_misses"] += 1
        return None

    def _cache_set(self, key: str, value: Any) -> None:
        self._cache[key] = (value, time.monotonic())
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_cache_size:
            self._cache.popitem(last=False)

    def invalidate_cache(self, filepath: str | os.PathLike[str]) -> None:
        if self._cache.pop(self._key(filepath), None) is not None:
            self.metrics["cache_invalidations"] += 1

    def clear_all_cache(self) -> int:
        count = len(self._cache)
        self._cache.clear()
        self.metrics["cache_invalidations"] += count
        return count

    def get_cache_stats(self) -> dict[str, Any]:
        lookups = self.metrics["cache_hits"] + self.metrics["cache_misses"]
        return {
            "cache_size": len(self._cache),
            "max_cache_size": self.max_cache_size,
            "cache_ttl": self.cache_ttl,
            "active_locks": len(self._locks),
            "locked_now": sum(1 for e in self._locks.values() if e.lock.locked()),
            "hit_rate": round(self.metrics["cache_hits"] / lookups * 100, 2) if lookups else 0.0,
            "total_reads": self.metrics["reads"],
            "total_writes": self.metrics["writes"],
            **self.metrics,
        }

    async def atomic_read(self, filepath: str | os.PathLike[str], use_cache: bool = True) -> str | None:
        key = self._key(filepath)
        if use_cache:
            cached = self._cache_get(key)
            if cached is not None:
                return cached
        else:
            self.metrics["cache_bypasses"] += 1

        async with self._lock(key):
            try:
                content = await asyncio.to_thread(Path(key).read_text, encoding="utf-8")
            except FileNotFoundError:
                return None
            except OSError as exc:
                self.metrics["read_failures"] += 1
                log.error("read failed for %s: %s", filepath, exc)
                return None
        self.metrics["reads"] += 1
        if use_cache:
            self._cache_set(key, content)
        return content

    async def atomic_write(
        self,
        filepath: str | os.PathLike[str],
        content: str,
        invalidate_cache_after: bool = True,
    ) -> bool:
        key = self._key(filepath)
        async with self._lock(key):
            for attempt in range(1, self.retries + 1):
                try:
                    await asyncio.to_thread(_write_atomic, Path(key), content)
                except OSError as exc:
                    if attempt < self.retries:
                        await asyncio.sleep(0.1 * attempt)
                        continue
                    self.metrics["write_failures"] += 1
                    log.error("write failed for %s after %d attempts: %s", filepath, attempt, exc)
                    return False
                break
        self.metrics["writes"] += 1
        if invalidate_cache_after:
            self.invalidate_cache(key)
        else:
            self._cache_set(key, content)
        return True

    async def atomic_read_json(self, filepath: str | os.PathLike[str], use_cache: bool = True) -> Any | None:
        content = await self.atomic_read(filepath, use_cache)
        if content is None:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            self.metrics["read_failures"] += 1
            log.error("invalid JSON in %s: %s", filepath, exc)
            return None

    async def atomic_write_json(
        self,
        filepath: str | os.PathLike[str],
        data: Any,
        invalidate_cache_after: bool = True,
        *,
        indent: int = 2,
    ) -> bool:
        try:
            content = json.dumps(data, indent=indent, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            self.metrics["write_failures"] += 1
            log.error("cannot serialise JSON for %s: %s", filepath, exc)
            return False
        return await self.atomic_write(filepath, content, invalidate_cache_after)


def _fsync_dir(directory: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_bytes_durable(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    _fsync_dir(path.parent)


def _write_atomic(path: Path, content: str) -> None:
    write_bytes_durable(path, content.encode("utf-8"))


global_file_handler = AtomicFileHandler()
