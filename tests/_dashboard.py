# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from zdbf.cogs.dashboard.actions import Dispatcher, catalogue
from zdbf.cogs.dashboard.capabilities import Policy
from zdbf.core.config import DashboardSettings

VECTORS = {
    "code": "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567",
    "bot_nonce": "0" * 32,
    "server_nonce": "f" * 32,
    "bot_id": "123456789012345678",
    "install_id": "abcdef0123456789",
    "code_id": "22441069e6aff07212be7b63fcb0b7db",
    "proof": "c4eb2303459e663a0346b9edd86a57ca11d1b6383b0bf40a9dbf66cfe90bd704",
    "ack": "568ad9ec6910ab12d93acdcee9486b260b65a5402ffbb1e8cb2c4246094a3419",
    "secret": "42d4c70c07d1fccfce84044dc8df5c2dee43e90c58f50a14e8249ec01c5a8397",
    "request": "058b8b37fe609f3092b1f2ca32ce22a83cb3e2c412bfe73d069440dbfa2c0d14",
    "response": "8cf4038a225aee62451b29a80495d35374bccc972f7d491ce9e0dfdfce62a989",
}


class FakeAudit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [{"action": r["action"], "outcome": r["outcome"]} for r in self.rows[-limit:]]

    def outcomes(self) -> list[str]:
        return [r["outcome"] for r in self.rows]


class FakeApprovals:
    def __init__(self) -> None:
        self.answer: tuple[bool, str] = (True, "Approved by tester.")
        self.calls: list[dict[str, Any]] = []
        self.pending = 0

    async def request(self, **kwargs: Any) -> tuple[bool, str]:
        self.calls.append(kwargs)
        return self.answer

    def clear_grants(self) -> None:
        return None


class FakeState:
    def __init__(self, cog: FakeCog) -> None:
        self.cog = cog
        self.sent = False

    def sample(self) -> None:
        return None

    def reset(self) -> None:
        self.sent = False

    async def changed(self, topics: Any, *, force: bool = False) -> dict[str, Any]:
        if self.sent and not force:
            return {}
        self.sent = True
        return {"meta": {"actions": catalogue(), "capabilities": self.cog.policy.describe(),
                         "locked": self.cog.policy.locked, "owners": ["1"], "bot": {"id": "1", "name": "Test"}}}


class FakeBot:
    def __init__(self) -> None:
        self.alerts = SimpleNamespace(send=self._alert, recent=[])
        self.alerted: list[str] = []
        self.latency = 0.05
        self.db = SimpleNamespace(fetchval=self._fetchval)

    async def _alert(self, system: str, message: str, level: str = "warning", **_: Any) -> bool:
        self.alerted.append(message)
        return True

    async def _fetchval(self, *_: Any, **__: Any) -> int:
        return 1

    async def wait_until_ready(self) -> None:
        return None


class FakeCog:
    def __init__(self, **settings: Any) -> None:
        self.settings = DashboardSettings(**settings)
        self.audit = FakeAudit()
        self.approvals = FakeApprovals()
        self.bot = FakeBot()
        self.results: list[dict[str, Any]] = []
        self.dispatcher = Dispatcher(self)  # type: ignore[arg-type]
        self.state = FakeState(self)
        self.client: Any = None
        self.link: Any = None

    @property
    def policy(self) -> Policy:
        return Policy(self.settings)

    async def post_result(self, result: dict[str, Any]) -> None:
        self.results.append(result)
        if self.client is not None:
            await self.client.post_result(result)

    def on_watch_changed(self) -> None:
        return None


def command(type_: str, *, command_id: str | None = None, args: dict[str, Any] | None = None,
            age: float = 0.0) -> dict[str, Any]:
    return {"id": command_id or f"{time.time_ns():032x}"[-32:], "type": type_, "args": args or {},
            "user": {"id": "7", "name": "tester", "role": "Admin"}, "issued_at": time.time() - age}
