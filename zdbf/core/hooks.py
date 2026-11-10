# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .bot import ZDBFBot

log = logging.getLogger("zdbf.hooks")

HookCallback = Callable[..., Awaitable[Any]]
BUILTIN_EVENTS = (
    "bot_ready",
    "guild_joined",
    "guild_left",
    "command_executed",
    "command_error",
    "extension_loaded",
    "extension_unloaded",
    "extension_reloaded",
    "scheduled_task",
    "cluster_broadcast",
)
__all__ = ["BUILTIN_EVENTS", "CircuitBreaker", "HookBus", "HookInfo"]


class CircuitBreaker:
    def __init__(self, threshold: int = 5, window: float = 300, cooldown: float = 60) -> None:
        self.threshold = threshold
        self.window = window
        self.cooldown = cooldown
        self._failures: dict[str, deque[float]] = {}
        self._open_until: dict[str, float] = {}

    def record_failure(self, hook_id: str) -> bool:
        now = time.monotonic()
        q = self._failures.setdefault(hook_id, deque())
        q.append(now)
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.threshold and hook_id not in self._open_until:
            self._open_until[hook_id] = now + self.cooldown
            return True
        return False

    def is_open(self, hook_id: str) -> bool:
        until = self._open_until.get(hook_id)
        if until is None:
            return False
        if time.monotonic() >= until:
            self.reset(hook_id)
            return False
        return True

    def reset(self, hook_id: str) -> None:
        self._failures.pop(hook_id, None)
        self._open_until.pop(hook_id, None)

    def open_hooks(self) -> list[str]:
        return [h for h in list(self._open_until) if self.is_open(h)]


@dataclass(eq=False)
class HookInfo:
    event: str
    callback: HookCallback
    priority: int = 0
    registered_at: float = field(default_factory=time.time)
    executions: int = 0
    failures: int = 0
    total_ms: float = 0.0

    @property
    def hook_id(self) -> str:
        cb = self.callback
        return f"{self.event}:{getattr(cb, '__module__', '?')}.{getattr(cb, '__qualname__', repr(cb))}"

    @property
    def avg_ms(self) -> float:
        return round(self.total_ms / self.executions, 2) if self.executions else 0.0


@dataclass(slots=True)
class HookHistoryEntry:
    event: str
    timestamp: float
    succeeded: int
    failed: int
    errors: list[str]
    queue_delay_ms: float
    avg_ms: float


class HookBus:
    def __init__(self, bot: ZDBFBot, *, timeout: float = 10.0, queue_size: int = 1000) -> None:
        self.bot = bot
        self.timeout = timeout
        self.hooks: dict[str, list[HookInfo]] = {}
        self.disabled: set[str] = set()
        self._pending_saves: set[asyncio.Task[None]] = set()
        self.breaker = CircuitBreaker()
        self.history: deque[HookHistoryEntry] = deque(maxlen=200)
        self._queue: asyncio.Queue[tuple[str, dict[str, Any], float]] = asyncio.Queue(maxsize=queue_size)
        self._worker: asyncio.Task[None] | None = None
        self._restarts = 0
        self.metrics = dict.fromkeys(("emitted", "executed", "failed", "dropped", "worker_restarts"), 0)

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name="zdbf-hook-worker")
            self._worker.add_done_callback(self._on_worker_done)

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    def _on_worker_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled() or task.exception() is None:
            return
        log.error("hook worker crashed", exc_info=task.exception())
        if self._restarts < 10:
            self._restarts += 1
            self.metrics["worker_restarts"] += 1
            self._worker = None
            self.start()

    @property
    def running(self) -> bool:
        return self._worker is not None and not self._worker.done()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def register(self, event: str, callback: HookCallback, priority: int = 0) -> bool:
        if not inspect.iscoroutinefunction(callback):
            log.error("hook callback must be async: %r", callback)
            return False
        bucket = self.hooks.setdefault(event, [])
        if any(h.callback == callback for h in bucket):
            return True
        bucket.append(HookInfo(event, callback, priority))
        bucket.sort(key=lambda h: h.priority, reverse=True)
        log.debug("hook registered %s -> %s (priority %d)", event, getattr(callback, "__qualname__", callback), priority)
        return True

    def unregister(self, event: str, callback: HookCallback) -> bool:
        bucket = self.hooks.get(event, [])
        before = len(bucket)
        bucket[:] = [h for h in bucket if h.callback != callback]
        return len(bucket) != before

    def unregister_module(self, module: str) -> int:
        removed = 0
        for bucket in self.hooks.values():
            keep = [h for h in bucket if not getattr(h.callback, "__module__", "").startswith(module)]
            removed += len(bucket) - len(keep)
            bucket[:] = keep
        return removed

    def find(self, hook_id: str) -> HookInfo | None:
        for bucket in self.hooks.values():
            for h in bucket:
                if h.hook_id == hook_id:
                    return h
        return None

    def all_hooks(self) -> list[HookInfo]:
        return [h for bucket in self.hooks.values() for h in bucket]

    KV_DISABLED = "eventhooks.disabled"

    async def load_disabled(self) -> None:
        self.disabled = set(await self.bot.db.kv_get(self.KV_DISABLED, []))

    def _persist_disabled(self) -> None:
        async def save() -> None:
            try:
                await self.bot.db.kv_set(self.KV_DISABLED, sorted(self.disabled))
            except Exception:
                log.exception("could not persist disabled hooks")

        with contextlib.suppress(RuntimeError):
            task = asyncio.get_running_loop().create_task(save())
            self._pending_saves.add(task)
            task.add_done_callback(self._pending_saves.discard)

    def disable(self, hook_id: str) -> bool:
        if self.find(hook_id) is None:
            return False
        self.disabled.add(hook_id)
        self._persist_disabled()
        return True

    def enable(self, hook_id: str) -> bool:
        if hook_id not in self.disabled and not self.breaker.is_open(hook_id):
            return False
        self.disabled.discard(hook_id)
        self.breaker.reset(hook_id)
        self._persist_disabled()
        return True

    async def emit(self, event: str, **payload: Any) -> int:
        receivers = self.hooks.get(event)
        if not receivers:
            return 0
        self.metrics["emitted"] += 1
        try:
            self._queue.put_nowait((event, payload, time.monotonic()))
        except asyncio.QueueFull:
            self.metrics["dropped"] += 1
            await self.bot.alerts.send("eventhooks", f"Hook queue full - dropped `{event}`", "error")
            return 0
        return len(receivers)

    async def emit_now(self, event: str, **payload: Any) -> HookHistoryEntry:
        return await self._dispatch(event, payload, time.monotonic())

    async def _run(self) -> None:
        while True:
            event, payload, queued_at = await self._queue.get()
            try:
                await self._dispatch(event, payload, queued_at)
            except Exception:
                log.exception("hook dispatch failed for %s", event)
            finally:
                self._queue.task_done()

    async def _dispatch(self, event: str, payload: dict[str, Any], queued_at: float) -> HookHistoryEntry:
        delay = (time.monotonic() - queued_at) * 1000
        ok = failed = 0
        errors: list[str] = []
        times: list[float] = []
        for hook in list(self.hooks.get(event, ())):
            hid = hook.hook_id
            if hid in self.disabled or self.breaker.is_open(hid):
                continue
            start = time.monotonic()
            try:
                await asyncio.wait_for(hook.callback(bot=self.bot, **payload), timeout=self.timeout)
            except Exception as exc:
                failed += 1
                hook.failures += 1
                self.metrics["failed"] += 1
                msg = "timed out" if isinstance(exc, TimeoutError) else f"{type(exc).__name__}: {exc}"
                errors.append(f"{hid}: {msg}")
                log.warning("hook %s failed: %s", hid, msg, exc_info=not isinstance(exc, TimeoutError))
                if self.breaker.record_failure(hid):
                    await self.bot.alerts.send(
                        "eventhooks", f"Circuit breaker opened for `{hid}` (paused {self.breaker.cooldown:.0f}s)", "warning"
                    )
            else:
                elapsed = (time.monotonic() - start) * 1000
                ok += 1
                hook.executions += 1
                hook.total_ms += elapsed
                times.append(elapsed)
                self.metrics["executed"] += 1
        entry = HookHistoryEntry(
            event=event,
            timestamp=time.time(),
            succeeded=ok,
            failed=failed,
            errors=errors[:5],
            queue_delay_ms=round(delay, 2),
            avg_ms=round(sum(times) / len(times), 2) if times else 0.0,
        )
        if ok or failed:
            self.history.append(entry)
        return entry
