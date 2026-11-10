# SPDX-License-Identifier: Apache-2.0
import asyncio

import pytest

from zdbf.core.database import Database


async def test_reader_never_sees_uncommitted_writes(tmp_cwd):
    db = Database("data/iso.db")
    await db.connect()
    try:
        await db.execute("CREATE TABLE t (v INTEGER)")
        inside = asyncio.Event()
        release = asyncio.Event()

        async def writer() -> None:
            async with db.transaction():
                await db.execute("INSERT INTO t VALUES (1)")
                assert await db.fetchval("SELECT COUNT(*) FROM t") == 1
                inside.set()
                await release.wait()

        task = asyncio.create_task(writer())
        await inside.wait()
        assert await db.fetchval("SELECT COUNT(*) FROM t") == 0
        release.set()
        await task
        assert await db.fetchval("SELECT COUNT(*) FROM t") == 1
    finally:
        await db.close()


async def test_failed_transaction_rolls_back_everything(tmp_cwd):
    db = Database("data/rb.db")
    await db.connect()
    try:
        await db.execute("CREATE TABLE t (v INTEGER)")
        with pytest.raises(RuntimeError):
            async with db.transaction():
                await db.execute("INSERT INTO t VALUES (1)")
                async with db.transaction():
                    await db.execute("INSERT INTO t VALUES (2)")
                raise RuntimeError("boom")
        assert await db.fetchval("SELECT COUNT(*) FROM t") == 0
    finally:
        await db.close()


async def test_corrupt_database_is_replaced_by_newest_backup(tmp_cwd):
    db = Database("data/zdbf.db")
    await db.connect()
    await db.set_guild_prefix(1, "?")
    await db.backup()
    await db.close()

    (tmp_cwd / "data" / "zdbf.db").write_bytes(b"this is not a sqlite database" * 200)
    for side in ("zdbf.db-wal", "zdbf.db-shm"):
        (tmp_cwd / "data" / side).unlink(missing_ok=True)

    db = Database("data/zdbf.db")
    await db.connect()
    try:
        assert db.recovered is not None and db.recovered[1] is not None
        assert await db.get_guild_prefix(1) == "?"
        assert list((tmp_cwd / "data").glob("zdbf.corrupt-*.db"))
        assert await db.quick_check() == "ok"
    finally:
        await db.close()


async def test_scheduled_restore_applies_on_next_start(tmp_cwd):
    db = Database("data/zdbf.db")
    await db.connect()
    await db.set_guild_prefix(1, "old")
    snapshot = await db.backup()
    await db.set_guild_prefix(1, "new")
    assert snapshot in db.list_backups()
    with pytest.raises(ValueError):
        db.request_restore(tmp_cwd / "elsewhere.db")
    db.request_restore(snapshot)
    assert (await db.stats())["restore_pending"]
    await db.close()

    db = Database("data/zdbf.db")
    await db.connect()
    try:
        assert await db.get_guild_prefix(1) == "old"
        assert not db.restore_marker.exists()
        assert list((tmp_cwd / "data").glob("zdbf.replaced-*.db"))
    finally:
        await db.close()


async def test_backup_save_is_atomic_with_its_audit_entry(tmp_cwd, monkeypatch):
    from zdbf.cogs.backup.snapshot import BackupStorage

    db = Database("data/zdbf.db")
    await db.connect()
    try:
        storage = BackupStorage(db, tmp_cwd / "data" / "backups")

        async def broken_audit(*args, **kwargs):
            raise RuntimeError("audit failed")

        monkeypatch.setattr(storage, "audit", broken_audit)
        with pytest.raises(RuntimeError):
            await storage.save(5, {"version": 1, "components": []}, label="x", user_id=1)
        assert await storage.list(5) == []
        assert not list((tmp_cwd / "data" / "backups").rglob("*.gz"))
    finally:
        await db.close()
