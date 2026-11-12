# SPDX-License-Identifier: Apache-2.0
import os

import pytest

from zdbf.cogs.dashboard.sandbox import Sandbox, SandboxError


@pytest.fixture
def box(tmp_path):
    (tmp_path / "extensions" / "pkg").mkdir(parents=True)
    (tmp_path / "extensions" / "hello.py").write_text("print('hi')")
    (tmp_path / "extensions" / "pkg" / "mod.py").write_text("x = 1")
    (tmp_path / "extensions" / ".env").write_text("TOKEN=secret")
    (tmp_path / "extensions" / "cache.db").write_text("db")
    (tmp_path / "data" / "dashboard").mkdir(parents=True)
    (tmp_path / "data" / "dashboard" / "link.json").write_text("{}")
    (tmp_path / "data" / "notes.txt").write_text("n")
    (tmp_path / ".env").write_text("DISCORD_TOKEN=secret")
    (tmp_path / "outside.txt").write_text("o")
    return Sandbox(tmp_path, ["extensions"], max_bytes=1024)


def test_allows_files_inside_a_root(box, tmp_path):
    assert box.resolve("extensions/hello.py") == tmp_path / "extensions" / "hello.py"
    assert box.resolve("extensions/pkg/./mod.py") == tmp_path / "extensions" / "pkg" / "mod.py"
    assert box.resolve("extensions\\pkg\\mod.py") == tmp_path / "extensions" / "pkg" / "mod.py"
    assert box.resolve("extensions/new_file.py").name == "new_file.py"
    assert box.relative(tmp_path / "extensions" / "pkg" / "mod.py") == "extensions/pkg/mod.py"


@pytest.mark.parametrize("path", [
    "", " ", ".", "/etc/passwd", "C:\\Windows\\system.ini", "../outside.txt", "extensions/../outside.txt",
    "extensions/pkg/../../.env", "outside.txt", ".env", "data/notes.txt", "extensionsX/hello.py",
    "extensions/\x00hello.py", "extensions/a\nb.py", "x" * 2000,
])
def test_rejects_paths_outside_the_roots(box, path):
    with pytest.raises(SandboxError):
        box.resolve(path)


@pytest.mark.parametrize("path", [
    "extensions/.env", "extensions/.env.local", "extensions/cache.db", "extensions/cache.db-wal",
    "extensions/.git/config", "extensions/pkg/id_rsa.pem", "extensions/zsync-zdbf-key.txt", "extensions/LINK.JSON",
])
def test_rejects_protected_names(box, path):
    with pytest.raises(SandboxError):
        box.resolve(path)


def test_protected_folders_stay_closed_even_when_listed_as_a_root(tmp_path, box):
    wide = Sandbox(tmp_path, ["data", "extensions"], max_bytes=1024)
    assert wide.resolve("data/notes.txt").name == "notes.txt"
    for path in ("data/dashboard/link.json", "data/dashboard/other.txt", "data/marketplace/x.txt", "data/db_backups/a.txt"):
        with pytest.raises(SandboxError):
            wide.resolve(path)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_rejects_symlink_escapes(box, tmp_path):
    try:
        os.symlink(tmp_path / "outside.txt", tmp_path / "extensions" / "link.py")
        os.symlink(tmp_path, tmp_path / "extensions" / "up")
        os.symlink(tmp_path / "extensions" / "hello.py", tmp_path / "extensions" / "alias.py")
    except OSError:
        pytest.skip("symlinks are not permitted here")
    with pytest.raises(SandboxError):
        box.resolve("extensions/link.py")
    with pytest.raises(SandboxError):
        box.resolve("extensions/up/outside.txt")
    with pytest.raises(SandboxError):
        box.resolve("extensions/up/.env")
    assert box.resolve("extensions/alias.py") == tmp_path / "extensions" / "hello.py"
    assert not box.visible(tmp_path / "extensions" / "link.py")


def test_root_that_is_a_symlink_out_of_the_bot_folder_is_refused(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "f.py").write_text("x")
    base = tmp_path / "bot"
    base.mkdir()
    try:
        os.symlink(elsewhere, base / "extensions")
    except OSError:
        pytest.skip("symlinks are not permitted here")
    with pytest.raises(SandboxError):
        Sandbox(base, ["extensions"], max_bytes=10).resolve("extensions/f.py")


def test_size_limit_and_visibility(box, tmp_path):
    box.check_size(1024)
    with pytest.raises(SandboxError):
        box.check_size(1025)
    assert box.visible(tmp_path / "extensions" / "hello.py")
    assert not box.visible(tmp_path / "extensions" / ".env")
    assert not box.visible(tmp_path / "extensions" / "cache.db")
    assert not box.visible(tmp_path / "extensions" / "__pycache__")
    assert not box.visible(tmp_path / "outside.txt")
    assert box.root_names() == ["extensions"]
