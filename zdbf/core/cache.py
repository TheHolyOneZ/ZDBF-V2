# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import time
from collections import OrderedDict
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")

__all__ = ["TTLCache"]


class TTLCache[K, V]:
    def __init__(self, ttl: float = 600, max_size: int = 10_000) -> None:
        self.ttl = ttl
        self.max_size = max_size
        self._data: OrderedDict[K, tuple[V, float]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: K) -> V | None:
        item = self._data.get(key)
        if item is None or time.monotonic() - item[1] > self.ttl:
            if item is not None:
                del self._data[key]
            self.misses += 1
            return None
        self._data.move_to_end(key)
        self.hits += 1
        return item[0]

    def set(self, key: K, value: V) -> None:
        self._data[key] = (value, time.monotonic())
        self._data.move_to_end(key)
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def invalidate(self, key: K) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def cleanup_expired(self) -> int:
        now = time.monotonic()
        stale = [k for k, (_, ts) in self._data.items() if now - ts > self.ttl]
        for k in stale:
            del self._data[k]
        return len(stale)

    def __len__(self) -> int:
        return len(self._data)
