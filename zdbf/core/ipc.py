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
import struct
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger("zdbf.ipc")

MAX_FRAME = 1_000_000
MAX_SKEW = 60.0
Handler = Callable[["Frame"], Awaitable[None]]

__all__ = ["Frame", "IPCClient", "IPCError", "IPCServer", "sign"]


class IPCError(Exception):
    pass


@dataclass
class Frame:
    op: str
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    target: str = "all"
    timestamp: float = field(default_factory=time.time)
    nonce: str = field(default_factory=lambda: secrets.token_hex(8))
    reply_to: str | None = None
    sig: str = ""

    def body(self) -> bytes:
        d = asdict(self)
        d.pop("sig")
        return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode()

    def encode(self, secret: str) -> bytes:
        self.sig = sign(secret, self.body())
        payload = json.dumps(asdict(self), separators=(",", ":"), default=str).encode()
        return struct.pack(">I", len(payload)) + payload

    @classmethod
    def decode(cls, payload: bytes, secret: str) -> Frame:
        try:
            raw = json.loads(payload)
            frame = cls(**{k: raw[k] for k in raw if k in cls.__dataclass_fields__})
        except (ValueError, TypeError) as exc:
            raise IPCError(f"malformed frame: {exc}") from exc
        if not hmac.compare_digest(frame.sig, sign(secret, frame.body())):
            raise IPCError("bad signature")
        if abs(time.time() - float(frame.timestamp)) > MAX_SKEW:
            raise IPCError("stale frame")
        return frame


def sign(secret: str, data: bytes) -> str:
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


async def _read(reader: asyncio.StreamReader, timeout: float = 120) -> bytes | None:
    try:
        header = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        (length,) = struct.unpack(">I", header)
        if length > MAX_FRAME:
            raise IPCError("frame too large")
        return await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
    except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
        return None


class _Peer:
    def __init__(self, name: str, secret: str) -> None:
        if len(secret) < 16:
            raise IPCError("SHARD_IPC_SECRET must be at least 16 characters")
        self.name = name
        self.secret = secret
        self._handlers: dict[str, list[Handler]] = {}
        self._seen: deque[str] = deque(maxlen=10_000)
        self._seen_set: set[str] = set()
        self._pending: dict[str, asyncio.Future[list[Frame]]] = {}
        self._collected: dict[str, list[Frame]] = {}
        self.stats = {"sent": 0, "received": 0, "rejected": 0}

    def on(self, op: str, handler: Handler) -> None:
        self._handlers.setdefault(op, []).append(handler)

    def _fresh(self, frame: Frame) -> bool:
        if frame.nonce in self._seen_set:
            return False
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(frame.nonce)
        self._seen_set.add(frame.nonce)
        return True

    async def _dispatch(self, frame: Frame) -> None:
        self.stats["received"] += 1
        if frame.reply_to and frame.reply_to in self._collected:
            self._collected[frame.reply_to].append(frame)
            return
        for handler in self._handlers.get(frame.op, []):
            try:
                await handler(frame)
            except Exception:
                log.exception("IPC handler for %s failed", frame.op)

    async def send(self, frame: Frame) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    async def request(self, op: str, data: dict[str, Any] | None = None, *, timeout: float = 3.0,
                      target: str = "all") -> list[Frame]:
        frame = Frame(op, data or {}, source=self.name, target=target)
        self._collected[frame.nonce] = []
        try:
            await self.send(frame)
            await asyncio.sleep(timeout)
            return self._collected[frame.nonce]
        finally:
            self._collected.pop(frame.nonce, None)

    async def reply(self, to: Frame, op: str, data: dict[str, Any]) -> None:
        await self.send(Frame(op, data, source=self.name, target=to.source, reply_to=to.nonce))


class IPCServer(_Peer):
    def __init__(self, host: str, port: int, secret: str, name: str) -> None:
        super().__init__(name, secret)
        self.host = host
        self.port = port
        self.clients: dict[str, asyncio.StreamWriter] = {}
        self.client_info: dict[str, dict[str, Any]] = {}
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        log.info("IPC server listening on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        for writer in list(self.clients.values()):
            writer.close()
        self.clients.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    @property
    def running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    async def _write(self, writer: asyncio.StreamWriter, frame: Frame) -> None:
        writer.write(frame.encode(self.secret))
        await writer.drain()
        self.stats["sent"] += 1

    async def send(self, frame: Frame) -> None:
        frame.source = frame.source or self.name
        targets = self.clients.items() if frame.target == "all" else \
            [(frame.target, self.clients[frame.target])] if frame.target in self.clients else []
        for name, writer in list(targets):
            if name == frame.source:
                continue
            with contextlib.suppress(ConnectionError, RuntimeError):
                await self._write(writer, Frame(**{**asdict(frame), "sig": ""}))

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        name: str | None = None
        try:
            challenge = secrets.token_hex(16)
            await self._write(writer, Frame("challenge", {"challenge": challenge}, source=self.name))
            raw = await _read(reader, timeout=10)
            if raw is None:
                return
            hello = Frame.decode(raw, self.secret)
            name = str(hello.data.get("cluster_name", ""))[:64]
            expected = sign(self.secret, f"{challenge}|{name}".encode())
            if hello.op != "auth" or not name or not hmac.compare_digest(str(hello.data.get("proof", "")), expected):
                raise IPCError("authentication failed")
            if name in self.clients or name == self.name:
                raise IPCError(f"cluster name {name!r} already connected")
            self.clients[name] = writer
            self.client_info[name] = {"address": str(addr), "connected_at": time.time(), "last_heartbeat": time.time(),
                                      **{k: hello.data.get(k) for k in ("shard_ids", "shard_count", "guild_count")}}
            await self._write(writer, Frame("auth_ok", {"server": self.name, "clusters": list(self.clients)},
                                            source=self.name, target=name))
            log.info("IPC client %s connected from %s", name, addr)
            await self.send(Frame("cluster_join", {"cluster_name": name}, source=self.name))
            while (raw := await _read(reader)) is not None:
                try:
                    frame = Frame.decode(raw, self.secret)
                except IPCError as exc:
                    self.stats["rejected"] += 1
                    log.warning("IPC frame from %s rejected: %s", name, exc)
                    continue
                if not self._fresh(frame):
                    continue
                frame.source = name
                if frame.op == "heartbeat":
                    self.client_info[name].update(last_heartbeat=time.time(), **{
                        k: frame.data.get(k) for k in ("guild_count", "latency_ms") if k in frame.data})
                    continue
                if frame.target != self.name:
                    await self.send(frame)
                if frame.target in ("all", self.name):
                    await self._dispatch(frame)
        except IPCError as exc:
            self.stats["rejected"] += 1
            log.warning("IPC connection from %s refused: %s", addr, exc)
            with contextlib.suppress(Exception):
                await self._write(writer, Frame("auth_failed", {"error": str(exc)}, source=self.name))
        finally:
            if name and self.clients.get(name) is writer:
                self.clients.pop(name, None)
                self.client_info.pop(name, None)
                log.info("IPC client %s disconnected", name)
                await self.send(Frame("cluster_leave", {"cluster_name": name}, source=self.name))
            writer.close()


class IPCClient(_Peer):
    def __init__(self, host: str, port: int, secret: str, name: str,
                 info: Callable[[], dict[str, Any]] | None = None) -> None:
        super().__init__(name, secret)
        self.host = host
        self.port = port
        self.info = info or dict
        self.connected = False
        self.server_name: str | None = None
        self.last_error: str | None = None
        self.reconnects = 0
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="zdbf-ipc-client")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._writer:
            self._writer.close()

    async def send(self, frame: Frame) -> None:
        if self._writer is None or not self.connected:
            raise IPCError("not connected")
        frame.source = self.name
        self._writer.write(frame.encode(self.secret))
        await self._writer.drain()
        self.stats["sent"] += 1

    async def _run(self) -> None:
        delay = 1.0
        while True:
            try:
                await self._session()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                log.warning("IPC client: %s - retrying in %.0fs", exc, delay)
            self.connected = False
            self.reconnects += 1
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _session(self) -> None:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        self._writer = writer
        try:
            raw = await _read(reader, timeout=10)
            if raw is None:
                raise IPCError("server closed the connection")
            challenge = Frame.decode(raw, self.secret)
            proof = sign(self.secret, f"{challenge.data['challenge']}|{self.name}".encode())
            writer.write(Frame("auth", {"cluster_name": self.name, "proof": proof, **self.info()},
                               source=self.name).encode(self.secret))
            await writer.drain()
            raw = await _read(reader, timeout=10)
            answer = Frame.decode(raw, self.secret) if raw else None
            if answer is None or answer.op != "auth_ok":
                raise IPCError((answer.data.get("error") if answer else None) or "authentication failed")
            self.server_name = answer.data.get("server")
            self.connected = True
            self.last_error = None
            log.info("IPC connected to %s as %s", self.server_name, self.name)
            heartbeat = asyncio.create_task(self._heartbeat())
            try:
                while (raw := await _read(reader)) is not None:
                    try:
                        frame = Frame.decode(raw, self.secret)
                    except IPCError as exc:
                        self.stats["rejected"] += 1
                        log.warning("IPC frame rejected: %s", exc)
                        continue
                    if self._fresh(frame):
                        await self._dispatch(frame)
            finally:
                heartbeat.cancel()
        finally:
            self.connected = False
            writer.close()

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(30)
            with contextlib.suppress(IPCError, ConnectionError):
                await self.send(Frame("heartbeat", self.info(), target=self.server_name or "all"))
