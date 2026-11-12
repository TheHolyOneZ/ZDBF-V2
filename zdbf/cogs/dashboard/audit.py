# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from ...core.database import utcnow_iso
from .capabilities import READ_ONLY

if TYPE_CHECKING:
    from ...core.database import Database

__all__ = ["AuditLog"]

log = logging.getLogger("zdbf.dashboard.audit")
KEEP = 5000


class AuditLog:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._writes = 0

    async def record(self, *, action: str, capability: str, outcome: str, user: dict[str, Any] | None = None,
                     command_id: str | None = None, detail: Any = None) -> None:
        user = user or {}
        text = detail if isinstance(detail, str) or detail is None else json.dumps(detail, default=str)
        level = logging.DEBUG if outcome == "ok" and capability in READ_ONLY else logging.INFO
        log.log(level, "%s | %s | %s | %s", outcome, action, user.get("name") or "-", (text or "")[:200])
        try:
            await self.db.execute(
                "INSERT INTO dashboard_audit (at, command_id, action, capability, user_id, user_name, outcome, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (utcnow_iso(), command_id, action[:100], capability[:40], str(user.get("id") or "")[:40],
                 str(user.get("name") or "")[:80], outcome[:20], (text or "")[:2000] or None),
            )
            self._writes += 1
            if self._writes % 200 == 0:
                await self.db.execute(
                    "DELETE FROM dashboard_audit WHERE id <= (SELECT MAX(id) FROM dashboard_audit) - ?", (KEEP,))
        except Exception:
            log.exception("could not write the dashboard audit log")

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT id, at, command_id, action, capability, user_id, user_name, outcome, detail "
            "FROM dashboard_audit ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),))
        return [dict(r) for r in rows]
