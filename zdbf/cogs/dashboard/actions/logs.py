# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from ..logtail import LEVELS, parse_lines, read_tail
from . import ActionContext, ActionError, action

HISTORY_BYTES = 2 * 1024 * 1024
SEARCH_BYTES = 16 * 1024 * 1024
LIMIT_MAX = 2000


@action("logs.history", "logs", timeout=30)
async def history(ctx: ActionContext) -> dict[str, Any]:
    level = ctx.text("level", default="DEBUG", max_length=10).upper()
    if level not in LEVELS:
        raise ActionError("Unknown log level.")
    query = ctx.text("query", default="", max_length=200).strip().lower()
    limit = ctx.integer("limit", default=500, minimum=1, maximum=LIMIT_MAX)
    folder = Path(ctx.bot.config.settings.logging.directory)
    path = folder / "zdbf.log"
    tail = ctx.cog.logtail
    clean = tail.clean if tail is not None else (lambda text: text)
    floor = LEVELS[level]

    def load() -> list[dict[str, Any]]:
        entries = parse_lines(read_tail(path, SEARCH_BYTES if query else HISTORY_BYTES), clean)
        picked = [
            e for e in entries
            if LEVELS.get(e["level"], 0) >= floor
            and (not query or query in e["msg"].lower() or query in e["name"].lower()
                 or query in (e.get("exc") or "").lower())
        ]
        return picked[-limit:]

    entries = await asyncio.to_thread(load)
    return {"entries": entries, "file": str(path), "exists": path.exists(), "now": round(time.time(), 3),
            "live": tail is not None and tail.loop is not None, "dropped": tail.dropped if tail else 0,
            "searched": bool(query)}
