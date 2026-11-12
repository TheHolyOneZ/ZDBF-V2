# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import importlib
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..capabilities import NAMES
from ..protocol import MAX_COMMAND_AGE
from ..sandbox import SandboxError

if TYPE_CHECKING:
    from ....core.bot import ZDBFBot
    from ..cog import Dashboard

__all__ = ["REGISTRY", "Action", "ActionContext", "ActionError", "Dispatcher", "action", "catalogue", "load_all"]

log = logging.getLogger("zdbf.dashboard.actions")
MODULES = ("system", "chat", "commands", "files", "extensions", "marketplace", "logs", "config", "servers",
           "backups", "automations", "runtime", "database", "tickets")
SEEN_MAX = 5000
Handler = Callable[["ActionContext"], Awaitable[Any]]
Summary = Callable[[dict[str, Any]], str]


class ActionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Action:
    type: str
    capability: str
    handler: Handler
    timeout: float = 60.0
    summary: Summary | None = None
    approval: bool = True


@dataclass(slots=True)
class ActionContext:
    cog: Dashboard
    bot: ZDBFBot
    command_id: str
    type: str
    args: dict[str, Any]
    user: dict[str, Any] = field(default_factory=dict)

    def text(self, name: str, *, default: str | None = None, max_length: int = 2000) -> str:
        value = self.args.get(name, default)
        if not isinstance(value, str) or (not value and default is None):
            raise ActionError(f"missing value: {name}")
        if len(value) > max_length:
            raise ActionError(f"{name} is too long")
        return value

    def integer(self, name: str, *, default: int | None = None, minimum: int | None = None,
                maximum: int | None = None) -> int:
        value = self.args.get(name, default)
        if isinstance(value, str) and value.lstrip("-").isdigit():
            value = int(value)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ActionError(f"missing value: {name}")
        if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
            raise ActionError(f"{name} is out of range")
        return value

    def flag(self, name: str, default: bool = False) -> bool:
        value = self.args.get(name, default)
        return value if isinstance(value, bool) else default

    async def progress(self, note: str) -> None:
        await self.cog.post_result({"id": self.command_id, "status": "running", "note": str(note)[:200]})


REGISTRY: dict[str, Action] = {}


def action(type_: str, capability: str, *, timeout: float = 60.0, summary: Summary | None = None,
           approval: bool = True) -> Callable[[Handler], Handler]:
    if capability not in NAMES:
        raise ValueError(f"unknown capability {capability!r}")

    def decorator(handler: Handler) -> Handler:
        REGISTRY[type_] = Action(type_, capability, handler, timeout, summary, approval)
        return handler

    return decorator


def load_all() -> None:
    for name in MODULES:
        importlib.import_module(f"{__name__}.{name}")


def catalogue() -> dict[str, str]:
    return {name: act.capability for name, act in sorted(REGISTRY.items())}


def _result(command_id: str, status: str, *, data: Any = None, error: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": command_id, "status": status}
    if data is not None:
        out["data"] = data
    if error:
        out["error"] = error[:1000]
    return out


class Dispatcher:
    def __init__(self, cog: Dashboard) -> None:
        self.cog = cog
        self._seen: OrderedDict[str, float] = OrderedDict()
        self.running = 0

    def _first_time(self, command_id: str) -> bool:
        if command_id in self._seen:
            return False
        self._seen[command_id] = time.time()
        while len(self._seen) > SEEN_MAX:
            self._seen.popitem(last=False)
        return True

    async def handle(self, raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        command_id = raw.get("id")
        type_ = raw.get("type")
        if not isinstance(command_id, str) or not command_id or len(command_id) > 64 or not isinstance(type_, str):
            return None
        if not self._first_time(command_id):
            return None
        args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
        audit = self.cog.audit
        act = REGISTRY.get(type_)
        if act is None:
            await audit.record(action=type_[:100], capability="-", outcome="unknown", user=user, command_id=command_id)
            return _result(command_id, "error", error="The bot does not know this action.")
        issued = raw.get("issued_at")
        if not isinstance(issued, int | float) or abs(time.time() - float(issued)) > MAX_COMMAND_AGE:
            await audit.record(action=type_, capability=act.capability, outcome="expired", user=user,
                               command_id=command_id)
            return _result(command_id, "expired", error="The command was too old when it reached the bot.")
        policy = self.cog.policy
        if not policy.allows(act.capability):
            reason = ("The dashboard link is locked to view-only." if policy.locked and act.capability in policy.enabled
                      else f"The capability `{act.capability}` is switched off on the bot.")
            await audit.record(action=type_, capability=act.capability, outcome="refused", user=user,
                               command_id=command_id, detail=reason)
            return _result(command_id, "denied", error=reason)
        summary = ""
        if act.summary is not None:
            try:
                summary = act.summary(args)
            except Exception:
                summary = ""
        if act.approval and policy.needs_approval(act.capability):
            await self.cog.post_result(_result(command_id, "awaiting_approval"))
            approved, note = await self.cog.approvals.request(
                capability=act.capability, action=type_, summary=summary, user=user,
                timeout=self.cog.settings.approval_timeout)
            if not approved:
                await audit.record(action=type_, capability=act.capability, outcome="denied", user=user,
                                   command_id=command_id, detail=note)
                return _result(command_id, "denied", error=note)
            if not self.cog.policy.allows(act.capability):
                await audit.record(action=type_, capability=act.capability, outcome="refused", user=user,
                                   command_id=command_id, detail="switched off while waiting for approval")
                return _result(command_id, "denied", error="The capability was switched off while waiting.")
        ctx = ActionContext(self.cog, self.cog.bot, command_id, type_, args, user)
        self.running += 1
        try:
            data = await asyncio.wait_for(act.handler(ctx), timeout=act.timeout)
        except (ActionError, SandboxError) as exc:
            await audit.record(action=type_, capability=act.capability, outcome="failed", user=user,
                               command_id=command_id, detail=str(exc))
            return _result(command_id, "error", error=str(exc))
        except TimeoutError:
            await audit.record(action=type_, capability=act.capability, outcome="timeout", user=user,
                               command_id=command_id, detail=summary)
            return _result(command_id, "error", error="The action took too long and was stopped.")
        except Exception as exc:
            log.exception("dashboard action %s failed", type_)
            await audit.record(action=type_, capability=act.capability, outcome="failed", user=user,
                               command_id=command_id, detail=f"{type(exc).__name__}: {exc}")
            return _result(command_id, "error", error=f"The action failed: {type(exc).__name__}. See the bot log.")
        finally:
            self.running -= 1
        if act.capability != "view":
            await audit.record(action=type_, capability=act.capability, outcome="ok", user=user,
                               command_id=command_id, detail=summary or None)
        return _result(command_id, "done", data=data if data is not None else {})
