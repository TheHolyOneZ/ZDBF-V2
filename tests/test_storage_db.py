# SPDX-License-Identifier: Apache-2.0
import asyncio

from zdbf.core.database import Database
from zdbf.core.storage import AtomicFileHandler


async def test_atomic_roundtrip_and_cache(tmp_cwd):
    h = AtomicFileHandler()
    assert await h.atomic_write_json("data/x.json", {"a": 1})
    assert await h.atomic_read_json("data/x.json") == {"a": 1}
    assert await h.atomic_read_json("data/x.json") == {"a": 1}
    assert h.metrics["cache_hits"] == 1
    assert await h.atomic_read("data/missing.json") is None


async def test_concurrent_writes_never_corrupt(tmp_cwd):
    h = AtomicFileHandler()
    await asyncio.gather(*(h.atomic_write_json("data/c.json", {"n": i, "pad": "x" * 2000}) for i in range(40)))
    data = await h.atomic_read_json("data/c.json", use_cache=False)
    assert isinstance(data, dict) and 0 <= data["n"] < 40
    assert not list((tmp_cwd / "data").glob("*.tmp"))


async def test_database_settings_permissions_stats(tmp_cwd):
    db = Database("data/test.db")
    await db.connect()
    try:
        assert await db.get_guild_prefix(1) is None
        await db.set_guild_prefix(1, "?")
        assert await db.get_guild_prefix(1) == "?"
        await db.set_guild_prefix(1, None)
        assert await db.get_guild_prefix(1) is None

        assert await db.add_command_role(1, "backup", 10)
        assert not await db.add_command_role(1, "backup", 10)
        await db.add_command_role(1, "backup create", 11)
        assert await db.list_command_permissions(1) == {"backup": [10], "backup create": [11]}
        assert await db.clear_command_roles(1, "backup") == 1

        await db.increment_command_usage("ping", 1)
        await db.increment_command_usage("ping", 1)
        assert await db.get_command_stats(1) == [("ping", 2)]
        assert await db.get_command_stats() == [("ping", 2)]

        await db.kv_set("k", {"x": [1]})
        assert await db.kv_get("k") == {"x": [1]}
        assert await db.integrity_check() == "ok"
        assert (await db.stats())["schema_version"] >= 2
        backup = await db.backup("data/bk")
        assert backup.exists()
    finally:
        await db.close()


async def test_migrations_idempotent(tmp_cwd):
    for _ in range(2):
        db = Database("data/m.db")
        await db.connect()
        rows = await db.fetchall("SELECT version FROM _zdbf_schema")
        await db.close()
    assert [r[0] for r in rows] == sorted({r[0] for r in rows})
