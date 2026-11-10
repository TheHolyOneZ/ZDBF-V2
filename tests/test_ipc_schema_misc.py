# SPDX-License-Identifier: Apache-2.0
import asyncio
import time

import pytest

from zdbf.cogs.automations.engine import check_conditions, render, validate_conditions
from zdbf.cogs.backup.snapshot import checksum, diff
from zdbf.cogs.compat import LEGACY_COMMANDS
from zdbf.core.ipc import Frame, IPCClient, IPCError, IPCServer
from zdbf.core.schema import validate_against
from zdbf.marketplace.client import Extension, safety_scan
from zdbf.utils import human_duration, parse_duration

SECRET = "s" * 32


def test_frame_signing_and_tamper_detection():
    raw = Frame("op", {"a": 1}, source="x").encode(SECRET)[4:]
    assert Frame.decode(raw, SECRET).data == {"a": 1}
    with pytest.raises(IPCError):
        Frame.decode(raw.replace(b'"a":1', b'"a":2'), SECRET)
    with pytest.raises(IPCError):
        Frame.decode(raw, "t" * 32)
    old = Frame("op", timestamp=time.time() - 3600)
    with pytest.raises(IPCError):
        Frame.decode(old.encode(SECRET)[4:], SECRET)


async def test_ipc_auth_and_relay(unused_tcp_port):
    server = IPCServer("127.0.0.1", unused_tcp_port, SECRET, "main")
    await server.start()
    a = IPCClient("127.0.0.1", unused_tcp_port, SECRET, "a")
    b = IPCClient("127.0.0.1", unused_tcp_port, SECRET, "b")
    evil = IPCClient("127.0.0.1", unused_tcp_port, "x" * 32, "evil")

    async def answer(frame):
        await b.reply(frame, "pong", {"from": "b"})

    b.on("ping", answer)
    for c in (a, b, evil):
        c.start()
    try:
        for _ in range(50):
            if a.connected and b.connected:
                break
            await asyncio.sleep(0.05)
        replies = await a.request("ping", timeout=0.5)
        assert [r.data["from"] for r in replies] == ["b"]
        assert not evil.connected and "evil" not in server.clients
    finally:
        for c in (a, b, evil):
            await c.stop()
        await server.stop()


def test_short_secret_rejected():
    with pytest.raises(IPCError):
        IPCServer("127.0.0.1", 1, "short", "x")


def test_schema_validation():
    schema = {"weather": {"type": dict, "children": {
        "api_key": {"type": str, "required": True},
        "interval": {"type": int, "min": 60, "max": 3600, "default": 300}}}}
    res = validate_against({"weather": {"interval": 10, "extra": 1}}, schema)
    assert any("api_key" in e for e in res.errors)
    assert any("below the minimum" in w for w in res.warnings)
    assert any("unknown key" in w for w in res.warnings)
    assert validate_against({"weather": {"api_key": "x", "interval": True}}, schema).errors


def test_conditions_and_render():
    parsed, err = validate_conditions('[{"type": "chance", "percent": 100}, {"type": "not_bot"}]')
    assert err is None and check_conditions(parsed)
    _, err = validate_conditions('[{"type": "nope"}]')
    assert err
    _, err = validate_conditions('[{"type": "time_range", "start": "9", "end": "10:00"}]')
    assert err
    assert render("Hi {user} {user.__class__} {x}", user="@me") == "Hi @me {user.__class__} {x}"


def test_backup_diff_and_checksum():
    old = {"roles": [{"name": "Mod", "color": 1}], "text_channels": [{"name": "general", "topic": "a"}]}
    new = {"roles": [{"name": "Mod", "color": 2}, {"name": "VIP"}], "text_channels": []}
    d = diff(old, new)
    assert d["roles"] == {"added": ["VIP"], "removed": [], "changed": ["Mod"]}
    assert d["channels"]["removed"] == ["#general"]
    assert checksum({"a": 1, "meta": {"x": 1}}) == checksum({"a": 1})


def test_marketplace_helpers():
    ext = Extension.from_api({"id": 1, "title": "My Cool Ext!", "fileType": "py", "owner_type": "admin"})
    assert ext.filename == "my_cool_ext.py" and ext.official
    scan = safety_scan("import subprocess\nimport discord\nasync def setup(bot):\n    eval('1')\n")
    assert scan["has_setup"] and "imports `subprocess`" in scan["flags"] and "calls `eval()`" in scan["flags"]
    assert not safety_scan("def (:")["ok"]


def test_legacy_aliases_target_existing_names():
    assert LEGACY_COMMANDS["backupcreate"] == "backup create"
    assert all(" " in v or v in ("stats",) for v in LEGACY_COMMANDS.values())


def test_utils():
    assert human_duration(3725) == "1h 2m 5s"
    assert parse_duration("1h30m") == 5400 and parse_duration("abc") is None
