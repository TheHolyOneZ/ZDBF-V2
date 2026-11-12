# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import deque
from typing import TYPE_CHECKING, Any

import aiohttp

from ... import __version__
from .link import Link
from .protocol import (
    MAX_SKEW,
    PAIR_PATH,
    PULL_PATH,
    PUSH_PATH,
    VERSION,
    ProtocolError,
    code_id,
    derive_secret,
    encode_body,
    pair_ack,
    pair_proof,
    request_signature,
    response_signature,
)
from .state import ALWAYS

if TYPE_CHECKING:
    from .cog import Dashboard

__all__ = ["DashboardClient", "LinkError", "LinkRejected", "pair"]

log = logging.getLogger("zdbf.dashboard.link")
USER_AGENT = f"ZDBF-Dashboard/{__version__}"
FAST_INTERVAL = 2.0
SAMPLE_INTERVAL = 5.0
IDLE_GAP = 8.0
HOLD_RETRY = 600.0
HOLD_PROBE = 4.0
MAX_EVENTS = 2000
EVENTS_PER_PUSH = 200
MAX_RESPONSE = 12 * 1024 * 1024


class LinkError(Exception):
    pass


class LinkRejected(LinkError):
    pass


def topics_digest(topics: set[str]) -> str:
    return hashlib.sha1(",".join(sorted(topics)).encode()).hexdigest()


def _session(timeout: float = 30) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout), headers={"User-Agent": USER_AGENT})


async def _read(resp: aiohttp.ClientResponse) -> bytes:
    parts: list[bytes] = []
    size = 0
    async for chunk in resp.content.iter_chunked(64 * 1024):
        size += len(chunk)
        if size > MAX_RESPONSE:
            raise LinkError("the website sent an oversized response")
        parts.append(chunk)
    return b"".join(parts)


async def pair(url: str, code: str, bot_id: str) -> Link:
    bot_nonce = secrets.token_hex(16)
    payload = {"v": VERSION, "code_id": code_id(code), "bot_nonce": bot_nonce, "bot_id": bot_id,
               "proof": pair_proof(code, bot_nonce, bot_id), "version": __version__}
    async with _session(20) as session:
        try:
            async with session.post(f"{url}/{PAIR_PATH}", json=payload, allow_redirects=False) as resp:
                status = resp.status
                body = await _read(resp)
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise LinkError(f"Could not reach the dashboard: {type(exc).__name__}. Check the address.") from exc
    if status in (301, 302, 303, 307, 308):
        raise LinkError("That address redirects somewhere else. Use the final address shown in your browser.")
    if status == 404:
        raise LinkError("No dashboard was found at that address. Check the folder name in the URL.")
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise LinkError(f"The website did not answer like a ZDBF Dashboard (HTTP {status}).")
    if status != 200 or not data.get("ok"):
        reasons = {
            "code": "The pairing code is wrong or has expired. Create a new one on the dashboard.",
            "rate": "Too many attempts. Wait a few minutes and create a new code.",
            "setup": "The dashboard has not finished setup yet. Open setup.php first.",
        }
        raise LinkError(reasons.get(str(data.get("error")), f"The website refused the pairing (HTTP {status})."))
    install_id, server_nonce = str(data.get("install_id", "")), str(data.get("server_nonce", ""))
    expected = pair_ack(code, bot_nonce, server_nonce, install_id)
    if not install_id or not hmac.compare_digest(expected, str(data.get("proof", ""))):
        raise LinkError("The website could not prove that it knows the pairing code. Nothing was saved.")
    return Link(url=url, install_id=install_id, bot_id=bot_id,
                secret=derive_secret(code, bot_nonce, server_nonce, install_id))


class DashboardClient:
    def __init__(self, cog: Dashboard, link: Link) -> None:
        self.cog = cog
        self.link = link
        self.session: aiohttp.ClientSession | None = None
        self.offset = 0.0
        self.gzip = True
        self.hold = 20.0
        self.hold_ok = True
        self._hold_failures = 0
        self._hold_retry_at = 0.0
        self.watch_active = False
        self.watch_topics: set[str] = set()
        self.watch_channels: set[str] = set()
        self.connected = False
        self.broken: str | None = None
        self.last_ok = 0.0
        self.last_error: str | None = None
        self.round_trip_ms: float | None = None
        self.stats = {"requests": 0, "failures": 0, "commands": 0, "events": 0}
        self._results: deque[dict[str, Any]] = deque()
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._acks: list[str] = []
        self._wake = asyncio.Event()
        self._force_state = True
        self._tasks: list[asyncio.Task[None]] = []
        self._jobs: set[asyncio.Task[None]] = set()

    def start(self) -> None:
        if self._tasks:
            return
        self.session = _session(60)
        self._force_state = True
        self._wake.set()
        self._tasks = [
            asyncio.create_task(self._guard(self._pull_loop), name="zdbf-dashboard-pull"),
            asyncio.create_task(self._guard(self._push_loop), name="zdbf-dashboard-push"),
            asyncio.create_task(self._guard(self._sample_loop), name="zdbf-dashboard-sample"),
        ]

    async def stop(self) -> None:
        for task in [*self._tasks, *self._jobs]:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []
        self.connected = False
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def _guard(self, loop: Any) -> None:
        try:
            await loop()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("dashboard link task stopped unexpectedly")

    def wake(self, *, force_state: bool = False) -> None:
        if force_state:
            self._force_state = True
        self._wake.set()

    async def post_result(self, result: dict[str, Any]) -> None:
        self._results.append(result)
        self._wake.set()

    def watching(self, topic: str) -> bool:
        return self.watch_active and topic in self.watch_topics

    def emit(self, topic: str, data: Any) -> None:
        self._events.append({"topic": topic, "data": data, "at": round(time.time(), 3)})
        self.stats["events"] += 1
        self._wake.set()

    async def call(self, path: str, payload: dict[str, Any], *, timeout: float = 20, retry_skew: bool = True) -> dict[str, Any]:
        if self.session is None:
            raise LinkError("the link is not running")
        body, encoding = encode_body(payload, compress=self.gzip)
        timestamp = str(int(time.time() + self.offset))
        nonce = secrets.token_hex(16)
        headers = {
            "Content-Type": "application/json" if encoding == "identity" else "application/octet-stream",
            "X-ZDBF-Install": self.link.install_id,
            "X-ZDBF-Timestamp": timestamp,
            "X-ZDBF-Nonce": nonce,
            "X-ZDBF-Encoding": encoding,
            "X-ZDBF-Signature": request_signature(self.link.secret, path, timestamp, nonce, body),
        }
        started = time.perf_counter()
        self.stats["requests"] += 1
        async with self.session.post(self.link.endpoint(path), data=body, headers=headers, allow_redirects=False,
                                     timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            status = resp.status
            raw = await _read(resp)
            sig = resp.headers.get("X-ZDBF-Signature", "")
            sig_ts = resp.headers.get("X-ZDBF-Timestamp", "")
        if status == 401:
            try:
                info = json.loads(raw)
            except ValueError:
                info = {}
            if retry_skew and info.get("error") == "skew" and isinstance(info.get("server_time"), int | float):
                self.offset = float(info["server_time"]) - time.time()
                log.warning("clock differs from the website by %.0f s - adjusting", self.offset)
                return await self.call(path, payload, timeout=timeout, retry_skew=False)
            raise LinkRejected(str(info.get("error") or "auth"))
        if status != 200:
            raise LinkError(f"HTTP {status}")
        expected = response_signature(self.link.secret, path, nonce, sig_ts, raw)
        if not sig or not hmac.compare_digest(expected, sig):
            raise LinkError("the response was not signed by the dashboard")
        if not sig_ts.isdigit() or abs(int(sig_ts) - (time.time() + self.offset)) > MAX_SKEW + timeout:
            raise LinkError("the response is stale")
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise LinkError("the response is not valid JSON") from exc
        if not isinstance(data, dict):
            raise LinkError("unexpected response")
        if path == PUSH_PATH:
            self.round_trip_ms = round((time.perf_counter() - started) * 1000, 1)
        self.last_ok = time.time()
        if not self.connected:
            log.info("dashboard link connected to %s", self.link.url)
        self.connected = True
        self.last_error = None
        return data

    def _apply(self, data: dict[str, Any]) -> None:
        features = data.get("features")
        if isinstance(features, dict):
            self.gzip = bool(features.get("gzip", True))
            hold = features.get("hold")
            if isinstance(hold, int | float):
                self.hold = float(max(0, min(hold, 55)))
        watch = data.get("watch")
        if isinstance(watch, dict):
            was = self.watch_active
            topics = {str(t) for t in watch.get("topics", []) if isinstance(t, str)}
            channels = {str(c) for c in watch.get("channels", []) if isinstance(c, str | int)}
            added = topics - self.watch_topics
            self.watch_active = bool(watch.get("active"))
            self.watch_topics, self.watch_channels = topics, channels
            if (self.watch_active and not was) or added:
                self.wake(force_state=True)
            self.cog.on_watch_changed()

    def _note_pull_failure(self, held: bool, elapsed: float) -> None:
        if not held or elapsed < HOLD_PROBE:
            return
        self._hold_failures += 1
        if self._hold_failures >= 2:
            self.hold_ok = False
            self._hold_retry_at = time.monotonic() + HOLD_RETRY
            log.info("held requests fail on this host - using short polling for a while")

    def _failed(self, exc: BaseException) -> None:
        self.stats["failures"] += 1
        error = str(exc) or type(exc).__name__
        if self.connected or self.last_error != error:
            log.warning("dashboard link problem: %s", error)
        self.connected = False
        self.last_error = error

    async def _reject(self, exc: LinkRejected, streak: int) -> bool:
        self._failed(exc)
        if streak < 3:
            return False
        self.broken = ("The website no longer accepts this bot's signature. It may have been reinstalled or "
                       "unpaired. Run /dashboard pair again.")
        log.error("dashboard link stopped: %s", self.broken)
        await self.cog.bot.alerts.send("dashboard", self.broken, "error")
        return True

    async def _pull_loop(self) -> None:
        await self.cog.bot.wait_until_ready()
        backoff, rejected = 1.0, 0
        while self.broken is None:
            if not self.hold_ok and time.monotonic() >= self._hold_retry_at:
                self.hold_ok, self._hold_failures = True, 0
            wait = self.hold_ok and self.hold > 0
            acks, self._acks = self._acks, []
            started = time.monotonic()
            try:
                data = await self.call(
                    PULL_PATH, {"v": VERSION, "wait": wait, "active": self.watch_active, "ack": acks,
                                "topics": topics_digest(self.watch_topics)},
                    timeout=self.hold + 15 if wait else 20)
            except LinkRejected as exc:
                rejected += 1
                if await self._reject(exc, rejected):
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            except (aiohttp.ClientError, TimeoutError, LinkError, ProtocolError) as exc:
                self._failed(exc)
                self._acks = acks + self._acks
                self._note_pull_failure(wait, time.monotonic() - started)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            backoff, rejected, self._hold_failures = 1.0, 0, 0
            self._apply(data)
            commands = data.get("commands") if isinstance(data.get("commands"), list) else []
            for raw in commands:
                if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                    self._acks.append(raw["id"])
                self.stats["commands"] += 1
                job = asyncio.create_task(self._run(raw))
                self._jobs.add(job)
                job.add_done_callback(self._jobs.discard)
            if commands:
                continue
            if not wait:
                await asyncio.sleep(FAST_INTERVAL if self.watch_active else min(self.cog.settings.idle_interval, 15))
            elif not self.watch_active:
                await asyncio.sleep(IDLE_GAP)

    async def _run(self, raw: Any) -> None:
        result = await self.cog.dispatcher.handle(raw)
        if result is not None:
            await self.post_result(result)

    async def _sample_loop(self) -> None:
        await self.cog.bot.wait_until_ready()
        while True:
            self.cog.state.sample()
            await asyncio.sleep(SAMPLE_INTERVAL)

    async def _push_loop(self) -> None:
        await self.cog.bot.wait_until_ready()
        backoff, rejected, last_idle_push = 1.0, 0, 0.0
        while self.broken is None:
            interval = FAST_INTERVAL if self.watch_active else self.cog.settings.idle_interval
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            self._wake.clear()
            if self._events and not self._results:
                await asyncio.sleep(0.15)
            force, self._force_state = self._force_state, False
            now = time.monotonic()
            if self.watch_active:
                topics = self.watch_topics | {"meta"}
            elif force or now - last_idle_push >= self.cog.settings.idle_interval:
                topics = set(ALWAYS)
                last_idle_push = now
            else:
                topics = {"meta"}
            results = list(self._results)
            events = [self._events.popleft() for _ in range(min(len(self._events), EVENTS_PER_PUSH))]
            try:
                state = await self.cog.state.changed(topics, force=force)
            except Exception:
                log.exception("could not collect dashboard state")
                state = {}
            if not (state or results or events):
                continue
            payload: dict[str, Any] = {"v": VERSION}
            if state:
                payload["state"] = state
            if results:
                payload["results"] = results
            if events:
                payload["events"] = events
            try:
                data = await self.call(PUSH_PATH, payload, timeout=30)
            except LinkRejected as exc:
                rejected += 1
                self._force_state = True
                if await self._reject(exc, rejected):
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            except (aiohttp.ClientError, TimeoutError, LinkError, ProtocolError) as exc:
                self._failed(exc)
                self._force_state = True
                self.cog.state.reset()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                self._wake.set()
                continue
            backoff, rejected = 1.0, 0
            for _ in results:
                self._results.popleft()
            self._apply(data)
            if self._events or self._results:
                self._wake.set()

    async def unpair(self) -> bool:
        try:
            await self.call(PUSH_PATH, {"v": VERSION, "unpair": True}, timeout=15)
        except (aiohttp.ClientError, TimeoutError, LinkError, ProtocolError):
            return False
        return True
