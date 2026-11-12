# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import time
from typing import Any

from . import ActionContext, action


@action("system.ping", "view", timeout=15)
async def ping(ctx: ActionContext) -> dict[str, Any]:
    start = time.perf_counter()
    await ctx.bot.db.fetchval("SELECT 1")
    return {
        "gateway_ms": round(ctx.bot.latency * 1000, 1) if ctx.bot.latency == ctx.bot.latency else None,
        "database_ms": round((time.perf_counter() - start) * 1000, 2),
        "time": time.time(),
    }


@action("system.audit", "view", timeout=15)
async def audit(ctx: ActionContext) -> dict[str, Any]:
    limit = ctx.integer("limit", default=100, minimum=1, maximum=500)
    return {"entries": await ctx.cog.audit.recent(limit)}
