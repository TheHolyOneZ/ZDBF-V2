# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import datetime as dt
import json
import logging
import re
import shutil
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, TypeVar

import aiosqlite

from .migrations import CORE_MIGRATIONS

log = logging.getLogger("zdbf.database")

__all__ = ["Database", "utcnow_iso"]

T = TypeVar("T")
RETRIES = 5
_in_transaction: contextvars.ContextVar[bool] = contextvars.ContextVar("zdbf_db_tx", default=False)


def utcnow_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _is_busy(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and any(
        w in str(exc).lower() for w in ("locked", "busy"))


class Database:
    def __init__(self, path: str | Path = "./data/zdbf.db", *, backup_dir: str | Path | None = None,
                 backup_keep: int = 7) -> None:
        self.path = Path(path)
        self.memory = str(path) == ":memory:"
        self.backup_dir = Path(backup_dir) if backup_dir else self.path.parent / "db_backups"
        self.backup_keep = backup_keep
        self._conn: aiosqlite.Connection | None = None
        self._reader: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()
        self._legacy_guild_conns: dict[int, aiosqlite.Connection] = {}
        self.query_count = 0
        self.retries = 0
        self.recovered: tuple[str, str | None] | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    @property
    def connected(self) -> bool:
        return self._conn is not None

    @property
    def restore_marker(self) -> Path:
        return self.path.with_name(self.path.name + ".restore")

    async def _open(self, *, readonly: bool = False) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        pragmas = ["PRAGMA busy_timeout=5000"]
        if readonly:
            pragmas.append("PRAGMA query_only=ON")
        else:
            pragmas += ["PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL", "PRAGMA foreign_keys=ON"]
        for pragma in pragmas:
            await conn.execute(pragma)
        return conn

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.memory:
            await asyncio.to_thread(self._apply_pending_restore)
            await self._check_or_recover()
        self._conn = await self._open()
        await self._migrate_core()
        self._reader = self._conn if self.memory else await self._open(readonly=True)
        log.info("database connected: %s", self.path)

    async def close(self) -> None:
        for conn in self._legacy_guild_conns.values():
            with contextlib.suppress(Exception):
                await conn.close()
        self._legacy_guild_conns.clear()
        if self._reader is not None and self._reader is not self._conn:
            with contextlib.suppress(Exception):
                await self._reader.close()
        self._reader = None
        if self._conn is not None:
            with contextlib.suppress(Exception):
                await self._conn.execute("PRAGMA optimize")
                await self._conn.commit()
                await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await self._conn.close()
            self._conn = None

    def _sidecars(self, path: Path) -> list[Path]:
        return [path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")]

    def _apply_pending_restore(self) -> None:
        marker = self.restore_marker
        if not marker.exists():
            return
        source = Path(marker.read_text(encoding="utf-8").strip())
        marker.unlink(missing_ok=True)
        if not source.exists():
            log.error("requested database restore source %s does not exist - ignored", source)
            return
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
        for f in self._sidecars(self.path):
            if f.exists():
                f.replace(f.with_name(f.name.replace(self.path.name, f"{self.path.stem}.replaced-{stamp}.db")))
        shutil.copy2(source, self.path)
        log.warning("restored database from %s (previous file kept as *.replaced-%s.db)", source, stamp)
        self.recovered = (f"{self.path.stem}.replaced-{stamp}.db", str(source))

    async def _check_or_recover(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        problem: str | None = None
        try:
            async with aiosqlite.connect(self.path) as probe:
                result = await (await probe.execute("PRAGMA quick_check")).fetchone()
                if result is None or result[0] != "ok":
                    problem = str(result[0] if result else "no result")
        except sqlite3.DatabaseError as exc:
            problem = str(exc)
        if problem is None:
            return
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
        corrupt = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}.db")
        for f in self._sidecars(self.path):
            if f.exists():
                f.replace(f.with_name(f.name.replace(self.path.name, corrupt.name)))
        backup = self.newest_backup()
        if backup is not None:
            shutil.copy2(backup, self.path)
        log.critical("database failed its integrity check (%s) - moved to %s, restored %s", problem, corrupt.name,
                     backup or "nothing (no backup found, starting empty)")
        self.recovered = (corrupt.name, str(backup) if backup else None)

    def list_backups(self) -> list[Path]:
        if not self.backup_dir.exists():
            return []
        return sorted(self.backup_dir.glob(f"{self.path.stem}-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)

    def newest_backup(self) -> Path | None:
        for candidate in self.list_backups():
            try:
                with sqlite3.connect(f"file:{candidate}?mode=ro", uri=True) as conn:
                    if conn.execute("PRAGMA quick_check").fetchone()[0] == "ok":
                        return candidate
            except sqlite3.DatabaseError:
                continue
        return None

    def request_restore(self, backup: str | Path) -> Path:
        path = Path(backup).resolve()
        if path.parent != self.backup_dir.resolve() or not path.exists():
            raise ValueError("not a backup of this database")
        self.restore_marker.write_text(str(path), encoding="utf-8")
        return path

    def cancel_restore(self) -> bool:
        existed = self.restore_marker.exists()
        self.restore_marker.unlink(missing_ok=True)
        return existed

    async def quick_check(self) -> str:
        return str(await self.fetchval("PRAGMA quick_check", default="unknown"))

    async def checkpoint(self) -> None:
        if self.memory or _in_transaction.get():
            return
        async with self._write_lock:
            await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    async def _migrate_core(self) -> None:
        await self.conn.execute(
            "CREATE TABLE IF NOT EXISTS _zdbf_schema ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        await self.conn.commit()
        rows = await (await self.conn.execute("SELECT version FROM _zdbf_schema")).fetchall()
        applied = {r[0] for r in rows}
        pending = [m for m in CORE_MIGRATIONS if m[0] not in applied]
        if pending and applied and not self.memory:
            target = await self.backup(label=f"pre-v{pending[0][0]}")
            log.info("backed up the database to %s before migrating", target.name)
        for version, name, sql in pending:
            log.info("applying core migration %04d_%s", version, name)
            async with self.transaction() as conn:
                for statement in _split_sql(sql):
                    await conn.execute(statement)
                await conn.execute(
                    "INSERT INTO _zdbf_schema (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, utcnow_iso()),
                )

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        if _in_transaction.get():
            yield self.conn
            return
        async with self._write_lock:
            token = _in_transaction.set(True)
            try:
                yield self.conn
            except BaseException:
                await self.conn.rollback()
                raise
            else:
                await self.conn.commit()
            finally:
                _in_transaction.reset(token)

    @property
    def in_transaction(self) -> bool:
        return _in_transaction.get()

    async def _retry(self, op: Callable[[], Awaitable[T]]) -> T:
        delay = 0.05
        for attempt in range(RETRIES):
            try:
                return await op()
            except sqlite3.OperationalError as exc:
                if not _is_busy(exc) or attempt == RETRIES - 1 or _in_transaction.get():
                    raise
                self.retries += 1
                log.warning("database busy (%s) - retry %d/%d", exc, attempt + 1, RETRIES)
                await asyncio.sleep(delay)
                delay *= 3
        raise AssertionError("unreachable")

    def _read_conn(self) -> aiosqlite.Connection:
        if _in_transaction.get() or self._reader is None:
            return self.conn
        return self._reader

    async def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
        self.query_count += 1

        async def op() -> int:
            async with self.transaction() as conn:
                cur = await conn.execute(sql, params)
                return cur.rowcount

        return await self._retry(op)

    async def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        self.query_count += 1
        rows = list(rows)

        async def op() -> None:
            async with self.transaction() as conn:
                await conn.executemany(sql, rows)

        await self._retry(op)

    async def fetchone(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> aiosqlite.Row | None:
        self.query_count += 1

        async def op() -> aiosqlite.Row | None:
            async with self._read_conn().execute(sql, params) as cur:
                return await cur.fetchone()

        return await self._retry(op)

    async def fetchall(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[aiosqlite.Row]:
        self.query_count += 1

        async def op() -> list[aiosqlite.Row]:
            async with self._read_conn().execute(sql, params) as cur:
                return list(await cur.fetchall())

        return await self._retry(op)

    async def fetchval(self, sql: str, params: Sequence[Any] | dict[str, Any] = (), default: Any = None) -> Any:
        row = await self.fetchone(sql, params)
        return row[0] if row is not None else default

    async def kv_get(self, key: str, default: Any = None) -> Any:
        raw = await self.fetchval("SELECT value FROM global_kv WHERE key = ?", (key,))
        return default if raw is None else json.loads(raw)

    async def kv_set(self, key: str, value: Any) -> None:
        await self.execute(
            "INSERT INTO global_kv (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value), utcnow_iso()),
        )

    async def kv_delete(self, key: str) -> None:
        await self.execute("DELETE FROM global_kv WHERE key = ?", (key,))

    async def get_setting(self, guild_id: int, key: str, default: Any = None) -> Any:
        raw = await self.fetchval(
            "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?", (guild_id, key)
        )
        return default if raw is None else json.loads(raw)

    async def set_setting(self, guild_id: int, key: str, value: Any) -> None:
        await self.execute(
            "INSERT INTO guild_settings (guild_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (guild_id, key, json.dumps(value), utcnow_iso()),
        )

    async def delete_setting(self, guild_id: int, key: str) -> bool:
        return bool(await self.execute("DELETE FROM guild_settings WHERE guild_id = ? AND key = ?", (guild_id, key)))

    async def all_settings(self, guild_id: int) -> dict[str, Any]:
        rows = await self.fetchall("SELECT key, value FROM guild_settings WHERE guild_id = ?", (guild_id,))
        return {r["key"]: json.loads(r["value"]) for r in rows}

    async def get_guild_prefix(self, guild_id: int) -> str | None:
        return await self.get_setting(guild_id, "prefix")

    async def set_guild_prefix(self, guild_id: int, prefix: str | None) -> None:
        if prefix is None:
            await self.delete_setting(guild_id, "prefix")
        else:
            await self.set_setting(guild_id, "prefix", prefix)

    async def get_guild_mention_prefix_enabled(self, guild_id: int) -> bool | None:
        return await self.get_setting(guild_id, "mention_prefix")

    async def set_guild_mention_prefix_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_setting(guild_id, "mention_prefix", bool(enabled))

    async def get_command_roles(self, guild_id: int, command: str) -> list[int]:
        rows = await self.fetchall(
            "SELECT role_id FROM command_permissions WHERE guild_id = ? AND command = ?", (guild_id, command)
        )
        return [r[0] for r in rows]

    async def add_command_role(self, guild_id: int, command: str, role_id: int) -> bool:
        return bool(
            await self.execute(
                "INSERT OR IGNORE INTO command_permissions (guild_id, command, role_id) VALUES (?, ?, ?)",
                (guild_id, command, role_id),
            )
        )

    async def remove_command_role(self, guild_id: int, command: str, role_id: int) -> bool:
        return bool(
            await self.execute(
                "DELETE FROM command_permissions WHERE guild_id = ? AND command = ? AND role_id = ?",
                (guild_id, command, role_id),
            )
        )

    async def clear_command_roles(self, guild_id: int, command: str) -> int:
        return await self.execute(
            "DELETE FROM command_permissions WHERE guild_id = ? AND command = ?", (guild_id, command)
        )

    async def list_command_permissions(self, guild_id: int) -> dict[str, list[int]]:
        rows = await self.fetchall(
            "SELECT command, role_id FROM command_permissions WHERE guild_id = ? ORDER BY command", (guild_id,)
        )
        out: dict[str, list[int]] = {}
        for r in rows:
            out.setdefault(r["command"], []).append(r["role_id"])
        return out

    async def increment_command_usage(self, command_name: str, guild_id: int | None = None) -> None:
        now = utcnow_iso()
        await self.executemany(
            "INSERT INTO command_stats (guild_id, command_name, usage_count, last_used) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(guild_id, command_name) DO UPDATE SET usage_count = usage_count + 1, last_used = excluded.last_used",
            [(0, command_name, now)] + ([(guild_id, command_name, now)] if guild_id else []),
        )

    async def get_command_stats(self, guild_id: int | None = None, limit: int = 25) -> list[tuple[str, int]]:
        rows = await self.fetchall(
            "SELECT command_name, usage_count FROM command_stats WHERE guild_id = ? "
            "ORDER BY usage_count DESC LIMIT ?",
            (guild_id or 0, limit),
        )
        return [(r[0], r[1]) for r in rows]

    async def purge_guild(self, guild_id: int) -> int:
        total = 0
        async with self.transaction() as conn:
            for table in ("guild_settings", "command_permissions", "command_stats", "scheduled_tasks", "automations"):
                cur = await conn.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
                total += cur.rowcount
        return total

    async def backup(self, directory: str | Path | None = None, keep: int | None = None, *,
                     label: str = "") -> Path:
        target_dir = Path(directory) if directory else self.backup_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = f"-{label}" if label else ""
        target = target_dir / f"{self.path.stem}-{dt.datetime.now(dt.UTC):%Y%m%d-%H%M%S}{suffix}.db"
        async with aiosqlite.connect(target) as dest:
            await self.conn.backup(dest)
        plain = re.compile(rf"^{re.escape(self.path.stem)}-\d{{8}}-\d{{6}}$")
        files = sorted(target_dir.glob(f"{self.path.stem}-*.db"))
        regular = [p for p in files if plain.match(p.stem)]
        for old in regular[:-(keep or self.backup_keep)]:
            old.unlink(missing_ok=True)
        labelled = [p for p in files if not plain.match(p.stem)]
        for old in labelled[:-5]:
            old.unlink(missing_ok=True)
        return target

    async def integrity_check(self) -> str:
        return str(await self.fetchval("PRAGMA integrity_check", default="unknown"))

    async def stats(self) -> dict[str, Any]:
        tables = [
            r[0]
            for r in await self.fetchall(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {t: await self.fetchval(f'SELECT COUNT(*) FROM "{t}"', default=0) for t in tables}
        page_count = await self.fetchval("PRAGMA page_count", default=0)
        page_size = await self.fetchval("PRAGMA page_size", default=0)
        return {
            "path": str(self.path),
            "size_bytes": page_count * page_size,
            "tables": counts,
            "queries": self.query_count,
            "legacy_guild_connections": len(self._legacy_guild_conns),
            "busy_retries": self.retries,
            "backups": len(self.list_backups()),
            "restore_pending": self.restore_marker.exists(),
            "schema_version": await self.fetchval("SELECT MAX(version) FROM _zdbf_schema", default=0),
        }

    async def _get_guild_connection(self, guild_id: int) -> aiosqlite.Connection:
        conn = self._legacy_guild_conns.get(guild_id)
        if conn is None:
            path = self.path.parent / str(guild_id) / "guild.db"
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            self._legacy_guild_conns[guild_id] = conn
        return conn

    async def cleanup_guild(self, guild_id: int) -> None:
        conn = self._legacy_guild_conns.pop(guild_id, None)
        if conn is not None:
            await conn.close()


def _split_sql(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]
