# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import re
from typing import Any

import aiosqlite

from . import ActionContext, ActionError, action

PAGE_MAX = 200
CELL_MAX = 2000
SECRET = re.compile(r"token|secret|password|passwd|api_key|apikey", re.IGNORECASE)


async def _connect(ctx: ActionContext) -> aiosqlite.Connection:
    path = ctx.bot.db.path.resolve()
    if not path.exists():
        raise ActionError("The database file does not exist yet.")
    return await aiosqlite.connect(f"{path.as_uri()}?mode=ro", uri=True)


async def _tables(conn: aiosqlite.Connection) -> list[str]:
    async with conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                            "ORDER BY name") as cur:
        return [r[0] for r in await cur.fetchall()]


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _cell(column: str, value: Any) -> Any:
    if value is None or isinstance(value, int | float):
        return value
    if SECRET.search(column):
        return "[hidden]"
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    text = str(value)
    return text if len(text) <= CELL_MAX else text[:CELL_MAX] + "…"


@action("database.tables", "database", timeout=30)
async def tables(ctx: ActionContext) -> dict[str, Any]:
    conn = await _connect(ctx)
    try:
        out = []
        for name in await _tables(conn):
            async with conn.execute(f"SELECT COUNT(*) FROM {_quote(name)}") as cur:
                count = (await cur.fetchone())[0]
            async with conn.execute(f"PRAGMA table_info({_quote(name)})") as cur:
                columns = [{"name": r[1], "type": r[2], "pk": bool(r[5])} for r in await cur.fetchall()]
            out.append({"name": name, "rows": count, "columns": columns})
    finally:
        await conn.close()
    path = ctx.bot.db.path
    return {"tables": out, "file": str(path), "size": path.stat().st_size if path.exists() else 0}


@action("database.rows", "database", timeout=30)
async def rows(ctx: ActionContext) -> dict[str, Any]:
    table = ctx.text("table", max_length=100)
    limit = ctx.integer("limit", default=50, minimum=1, maximum=PAGE_MAX)
    offset = ctx.integer("offset", default=0, minimum=0)
    search = ctx.text("search", default="", max_length=200).strip()
    descending = ctx.flag("desc", True)
    conn = await _connect(ctx)
    try:
        if table not in await _tables(conn):
            raise ActionError("That table does not exist.")
        async with conn.execute(f"PRAGMA table_info({_quote(table)})") as cur:
            info = await cur.fetchall()
        columns = [r[1] for r in info]
        order = ctx.text("order", default="", max_length=100) or next((r[1] for r in info if r[5]), "rowid")
        if order != "rowid" and order not in columns:
            raise ActionError("Unknown column.")
        where, params = "", []
        if search and any(not SECRET.search(c) for c in columns):
            where = " WHERE " + " OR ".join(f"CAST({_quote(c)} AS TEXT) LIKE ?" for c in columns if not SECRET.search(c))
            params = [f"%{search}%"] * sum(1 for c in columns if not SECRET.search(c))
        async with conn.execute(f"SELECT COUNT(*) FROM {_quote(table)}{where}", params) as cur:
            total = (await cur.fetchone())[0]
        sql = (f"SELECT * FROM {_quote(table)}{where} ORDER BY {_quote(order) if order != 'rowid' else 'rowid'} "
               f"{'DESC' if descending else 'ASC'} LIMIT ? OFFSET ?")
        async with conn.execute(sql, [*params, limit, offset]) as cur:
            data = [[_cell(columns[i], v) for i, v in enumerate(r)] for r in await cur.fetchall()]
    finally:
        await conn.close()
    return {"table": table, "columns": columns, "rows": data, "total": total, "offset": offset, "limit": limit,
            "order": order, "desc": descending}
