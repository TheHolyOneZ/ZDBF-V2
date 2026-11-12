# SPDX-License-Identifier: Apache-2.0
import base64
import hashlib
import logging
import threading
from types import SimpleNamespace

import pytest
from _dashboard import FakeCog, command

from zdbf.cogs.dashboard import actions
from zdbf.cogs.dashboard.actions import config as config_actions
from zdbf.cogs.dashboard.actions import extensions as ext_actions
from zdbf.cogs.dashboard.logtail import LogTail, parse_lines, redactor
from zdbf.cogs.dashboard.sandbox import Sandbox
from zdbf.core.config import Config

TOKEN = ".".join(["MTIzNDU2Nzg5MDEyMzQ1Njc4", "GAbCdE", "abcdefghijklmnopqrstuvwxyz0123456789AB"])
OTHER = ".".join(["MTAxMjM0NTY3ODkwMTIzNDU2Nzg5", "Xyz123", "abcdefghijklmnopqrstuvwxyz12"])


class FilesCog(FakeCog):
    @property
    def sandbox(self) -> Sandbox:
        return Sandbox(".", self.settings.file_roots, max_bytes=self.settings.max_file_kb * 1024)


class FakeExt:
    directory = "extensions"

    def is_builtin(self, module):
        return module.startswith("zdbf.")

    def path_for(self, module):
        return None

    def module_for(self, name):
        if name.startswith("zdbf."):
            return name
        return {"admin": "zdbf.cogs.admin"}.get(name, f"extensions.{name}")

    def short_name(self, module):
        return module.split(".")[-1]


@pytest.fixture
def cog(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    actions.load_all()
    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "hello.py").write_text("print('hi')\n")
    (tmp_path / "extensions" / ".env").write_text("SECRET=1\n")
    (tmp_path / "data").mkdir()
    cog = FilesCog(capabilities=["view", "files.read", "files.write", "config", "extensions"],
                   approval=["files.write", "config"], max_file_kb=64)
    cog.bot.ext = FakeExt()
    cog.bot.extensions = {}
    return cog


async def run(cog, type_, **args):
    result = await cog.dispatcher.handle(command(type_, args=args))
    return result


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


async def test_listing_hides_protected_files(cog):
    result = await run(cog, "files.list", path="extensions")
    assert result["status"] == "done"
    assert [i["name"] for i in result["data"]["items"]] == ["hello.py"]
    for path in ("extensions/.env", "../etc/passwd", "data", "extensions/../config.toml"):
        result = await run(cog, "files.read", path=path)
        assert result["status"] == "error", path


async def test_read_returns_content_and_hash(cog):
    result = await run(cog, "files.read", path="extensions/hello.py")
    data = result["data"]
    assert base64.b64decode(data["data"]) == b"print('hi')\n" and data["eof"]
    assert data["sha256"] == hashlib.sha256(b"print('hi')\n").hexdigest()


async def test_write_needs_approval_and_checks_the_version(cog):
    result = await run(cog, "files.write", path="extensions/hello.py", data=b64(b"new"), expect="0" * 64)
    assert cog.approvals.calls and result["status"] == "error" and "changed on the bot" in result["error"]
    sha = hashlib.sha256(b"print('hi')\n").hexdigest()
    result = await run(cog, "files.write", path="extensions/hello.py", data=b64(b"new\n"), expect=sha)
    assert result["status"] == "done" and result["data"]["trash"]
    assert open("extensions/hello.py", "rb").read() == b"new\n"
    trash = (await run(cog, "files.trash"))["data"]["items"]
    assert trash[0]["reason"] == "replaced" and trash[0]["path"] == "extensions/hello.py"


async def test_create_refuses_existing_and_size_limit(cog):
    result = await run(cog, "files.write", path="extensions/hello.py", data=b64(b"x"), create=True)
    assert "already exists" in result["error"]
    result = await run(cog, "files.write", path="extensions/big.py", data=b64(b"x" * 70 * 1024), create=True)
    assert "larger than the limit" in result["error"]
    result = await run(cog, "files.write", path="extensions/.env.local", data=b64(b"x"), create=True)
    assert result["status"] == "error"


async def test_chunked_upload_without_approval_per_piece(cog):
    upload = "a" * 32
    body = bytes(range(256)) * 100
    first = await run(cog, "files.stage", upload=upload, total=len(body), offset=0, data=b64(body[:10000]))
    assert first["data"]["received"] == 10000
    wrong = await run(cog, "files.stage", upload=upload, total=len(body), offset=5, data=b64(body[10000:]))
    assert "out of step" in wrong["error"]
    await run(cog, "files.stage", upload=upload, total=len(body), offset=10000, data=b64(body[10000:]))
    assert cog.approvals.calls == []
    result = await run(cog, "files.write", path="extensions/blob.bin", upload=upload, size=len(body), create=True)
    assert result["status"] == "done" and open("extensions/blob.bin", "rb").read() == body
    assert len(cog.approvals.calls) == 1
    bad = await run(cog, "files.stage", upload="../../x", total=10, offset=0, data=b64(b"x"))
    assert bad["status"] == "error"


async def test_rename_delete_and_restore(cog):
    assert (await run(cog, "files.mkdir", path="extensions", name="pkg"))["status"] == "done"
    assert (await run(cog, "files.mkdir", path="extensions", name=".."))["status"] == "error"
    renamed = await run(cog, "files.rename", path="extensions/hello.py", name="hey.py")
    assert renamed["data"]["path"] == "extensions/hey.py"
    assert (await run(cog, "files.rename", path="extensions/hey.py", name="../x.py"))["status"] == "error"
    assert (await run(cog, "files.delete", path="extensions"))["status"] == "error"
    deleted = await run(cog, "files.delete", path="extensions/hey.py")
    assert deleted["status"] == "done"
    import os
    assert not os.path.exists("extensions/hey.py")
    restored = await run(cog, "files.restore", id=deleted["data"]["trash"])
    assert restored["status"] == "done" and os.path.exists("extensions/hey.py")
    assert (await run(cog, "files.trash"))["data"]["items"] == []


async def test_extension_actions_refuse_builtin_modules(cog):
    for name in ("admin", "zdbf.cogs.dashboard", "dashboard"):
        result = await run(cog, "extensions.reload", name=name)
        assert result["status"] == "error" and "Built-in" in result["error"], name
    assert ext_actions.listing


def test_protected_config_keys():
    old = {"bot": {"prefix": "!", "owner_ids": []}, "modules": {"dashboard": True}, "dashboard": {"locked": False}}
    new = {"bot": {"prefix": "?", "owner_ids": [1]}, "modules": {"dashboard": True}, "dashboard": {"locked": True}}
    assert config_actions.protected_changes(old, new) == ["dashboard", "bot.owner_ids"]
    assert config_actions.changed_keys(old, new) == ["bot.owner_ids", "bot.prefix", "dashboard.locked"]
    for key in ("dashboard.capabilities", "modules.dashboard", "bot.owner_ids", "modules"):
        assert config_actions.touches_protected(key), key
    assert not config_actions.touches_protected("modules.backup")
    assert config_actions.needs_restart(["bot.prefix", "database.path", "logging.level"]) == ["database.path", "logging.level"]


async def test_config_write_keeps_a_copy_and_refuses_protected_changes(cog, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(Config.default_template(), encoding="utf-8")
    config = Config(path)
    config.overrides_path = tmp_path / "data" / "overrides.json"
    config.load()
    cog.bot.config = config
    cog.bot.prefix_cache = SimpleNamespace(clear=lambda: None)
    text = path.read_text()
    read = await run(cog, "config.read")
    assert read["status"] == "done" and not cog.approvals.calls
    assert any(f["key"] == "bot.owner_ids" and f["protected"] for s in read["data"]["sections"] for f in s["fields"])
    sneaky = text.replace("locked = false", "locked = true")
    assert sneaky != text
    check = await run(cog, "config.validate", text=sneaky)
    assert check["data"]["protected"] == ["dashboard"] and not check["data"]["ok"]
    refused = await run(cog, "config.write", text=sneaky)
    assert "cannot change dashboard" in refused["error"] and path.read_text() == text
    broken = await run(cog, "config.write", text="[bot\nprefix=")
    assert "not valid TOML" in broken["error"]
    good = text.replace('prefix = "!"', 'prefix = "?"', 1)
    done = await run(cog, "config.write", text=good, expect=read["data"]["sha256"])
    assert done["status"] == "done" and done["data"]["changes"] == ["bot.prefix"]
    assert config.settings.bot.prefix == "?" and len(done["data"]["history"]) == 1
    stale = await run(cog, "config.write", text=text, expect=read["data"]["sha256"])
    assert "changed on the bot" in stale["error"]
    copy = await run(cog, "config.backup", name=done["data"]["history"][0]["name"])
    assert copy["data"]["text"] == text
    assert (await run(cog, "config.backup", name="../../.env"))["status"] == "error"
    assert "cannot change" in (await run(cog, "config.set", key="dashboard.locked", value=False))["error"]
    assert "cannot change" in (await run(cog, "config.set", key="bot.owner_ids", value=[1]))["error"]
    ok = await run(cog, "config.set", key="backup.max_per_guild", value=7)
    assert ok["status"] == "done" and ok["data"]["override"] and config.get("backup.max_per_guild") == 7
    bad = await run(cog, "config.set", key="backup.max_per_guild", value="many")
    assert bad["status"] == "error"


def test_redactor_and_log_parsing():
    clean = redactor([TOKEN, "short", "ipc-secret-value"])
    assert "[hidden]" in clean(f"token {TOKEN}") and TOKEN not in clean(f"token {TOKEN}")
    assert clean(f"other {OTHER}").count("[hidden token]") == 1
    assert clean("ipc-secret-value here") == "[hidden] here" and clean("short") == "short"
    lines = [
        "2026-11-11 10:00:00,123 | INFO     | zdbf.bot | started",
        "2026-11-11 10:00:01,000 | ERROR    | zdbf.ext | boom",
        "Traceback (most recent call last):",
        '  File "x.py", line 1',
        "ValueError: bad",
    ]
    entries = parse_lines(lines, clean)
    assert [e["level"] for e in entries] == ["INFO", "ERROR"]
    assert entries[1]["exc"].endswith("ValueError: bad") and entries[0]["name"] == "zdbf.bot"


async def test_log_tail_publishes_from_threads_and_limits_rate():
    import asyncio

    got = []
    tail = LogTail(got.append, redactor([TOKEN]))
    tail.attach(asyncio.get_running_loop())
    logger = logging.getLogger("zdbf.test.tail")
    logger.setLevel(logging.INFO)
    try:
        logger.info("hello %s", TOKEN)
        thread = threading.Thread(target=lambda: logger.warning("from a thread"))
        thread.start()
        thread.join()
        await asyncio.sleep(0.05)
        assert [e["msg"] for e in got][:2] == ["hello [hidden]", "from a thread"]
        for i in range(200):
            logger.info("flood %d", i)
        await asyncio.sleep(0.05)
        assert len(got) <= 62 and tail.dropped > 0 and len(tail.buffer) >= 150
    finally:
        tail.detach()


async def test_folder_archive_leaves_out_protected_files(cog, tmp_path):
    import io
    import zipfile

    (tmp_path / "extensions" / "pkg").mkdir()
    (tmp_path / "extensions" / "pkg" / "mod.py").write_text("x = 1\n")
    (tmp_path / "extensions" / "pkg" / "__pycache__").mkdir()
    (tmp_path / "extensions" / "pkg" / "__pycache__" / "mod.pyc").write_bytes(b"\0")
    (tmp_path / "extensions" / "data.db").write_bytes(b"db")
    made = await run(cog, "files.archive", path="extensions")
    assert made["status"] == "done" and made["data"]["files"] == 2
    blob, offset = b"", 0
    while True:
        part = (await run(cog, "files.archive_read", id=made["data"]["id"], offset=offset))["data"]
        chunk = base64.b64decode(part["data"])
        blob += chunk
        offset += len(chunk)
        if part["eof"]:
            break
    names = sorted(zipfile.ZipFile(io.BytesIO(blob)).namelist())
    assert names == ["extensions/hello.py", "extensions/pkg/mod.py"]
    again = await run(cog, "files.archive_read", id=made["data"]["id"], offset=0)
    assert again["status"] == "error"
    assert (await run(cog, "files.archive_read", id="../../x", offset=0))["status"] == "error"
