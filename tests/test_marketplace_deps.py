# SPDX-License-Identifier: Apache-2.0
import sys
from types import SimpleNamespace

import discord
import pytest

from zdbf.marketplace import deps
from zdbf.marketplace.client import Extension, safety_scan
from zdbf.marketplace.cog import InstallView

SOURCE = """
import json
import aiohttp
import discord
from discord.ext import commands
import cv2
import zz_needed_pkg
from . import helpers
from typing import TYPE_CHECKING
try:
    import zz_optional_one
except ImportError:
    zz_optional_one = None
try:
    from zz_optional_two import thing
except (ModuleNotFoundError, OSError):
    thing = None
if TYPE_CHECKING:
    import zz_typing_only

async def setup(bot):
    pass
"""


def test_scan_marks_guarded_imports_optional():
    scan = safety_scan(SOURCE)
    assert scan["ok"] and scan["has_setup"]
    assert set(scan["optional_imports"]) == {"zz_optional_one", "zz_optional_two", "zz_typing_only"}
    assert "zz_needed_pkg" in scan["imports"] and "zz_needed_pkg" not in scan["optional_imports"]


def test_required_packages_skips_stdlib_installed_optional_and_framework():
    scan = safety_scan(SOURCE)
    pkgs = deps.required_packages(scan)
    assert "zz_needed_pkg" in pkgs
    assert set(pkgs) <= {"zz_needed_pkg", "opencv-python"}
    assert "zz_needed_pkg" not in deps.required_packages(scan, own_module="zz_needed_pkg")
    assert deps.packages_for(["zz_optional_one"]) == ["zz_optional_one"]


def test_pip_names_and_unsafe_names():
    assert deps.pip_name("PIL") == "Pillow"
    assert deps.pip_name("google.generativeai") == "google-generativeai"
    assert not deps.PACKAGE_RE.match("--index-url=https://evil")
    assert not deps.PACKAGE_RE.match("pkg; rm -rf /")
    assert deps.PACKAGE_RE.match("python-dateutil")


async def test_install_refuses_unusual_names():
    res = await deps.install_packages(["--index-url=https://evil", "ok-pkg"])
    assert not res.ok and "unusual" in (res.error or "")
    assert (await deps.install_packages([])).ok


def test_install_command_falls_back_to_uv(monkeypatch):
    monkeypatch.setattr(deps, "_has_pip", lambda: False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    tool, args = deps.install_command(["requests"])
    assert tool == "uv" and args[:3] == ["/usr/bin/uv", "pip", "install"] and sys.executable in args
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    assert deps.install_command(["requests"]) is None


async def test_install_reports_exit_code(monkeypatch):
    monkeypatch.setattr(deps, "install_command",
                        lambda pk: ("pip", [sys.executable, "-c", "import sys; print('done'); sys.exit(int(sys.argv[1]))", pk[0]]))
    ok = await deps.install_packages(["0"])
    assert ok.ok and ok.output == ["done"]
    bad = await deps.install_packages(["3"])
    assert not bad.ok and "code 3" in (bad.error or "")


def _ext():
    return Extension(id=7, title="Demo", description="", details="", version="1.0.0", creator="x",
                     owner_type="user", status="working", date="", changelog="", file_type="py", custom_url="")


class FakeInteraction:
    def __init__(self, user_id=1):
        self.user = SimpleNamespace(id=user_id)
        self.done = False
        self.sent = []
        self.response = SimpleNamespace(is_done=lambda: self.done, defer=self._defer,
                                        send_message=self._send, edit_message=self._edit)

    async def _defer(self, *a, **k):
        self.done = True

    async def _send(self, *a, **k):
        self.done = True
        self.sent.append(k)

    async def _edit(self, *a, **k):
        self.done = True

    async def edit_original_response(self, *a, **k):
        return None


def _cog(tmp_path, events, *, owner=True, auto=True):
    async def reload(name):
        events.append(("reload", name))
        return SimpleNamespace(ok=True, action="load", elapsed_ms=5.0, error=None)

    async def is_owner(user):
        return owner

    async def record_install(ext, source):
        events.append(("record", ext.filename))

    bot = SimpleNamespace(
        config=SimpleNamespace(settings=SimpleNamespace(marketplace=SimpleNamespace(auto_install_packages=auto))),
        ext=SimpleNamespace(directory=tmp_path, reload=reload, module_for=lambda n: f"extensions.{n}"),
        extensions={}, plugins=SimpleNamespace(preflight=lambda m, p: []), is_owner=is_owner)
    return SimpleNamespace(bot=bot, record_install=record_install)


def _labels(view):
    return [c.label for c in view.walk_children() if isinstance(c, discord.ui.Button)]


async def test_install_and_load_installs_packages_first(tmp_path, monkeypatch):
    events = []

    async def fake_install(packages):
        events.append(("pip", tuple(packages)))
        return deps.PipResult(True, packages, "pip", ["Successfully installed"])

    monkeypatch.setattr("zdbf.marketplace.cog.install_packages", fake_install)
    source = "import zz_needed_pkg\nasync def setup(bot):\n    pass\n"
    view = InstallView(_cog(tmp_path, events), _ext(), source, safety_scan(source), author_id=1)
    view.build()
    assert view.packages == ["zz_needed_pkg"]
    assert _labels(view)[:2] == ["Install and load", "Install file only"]
    await view._install_and_load(FakeInteraction())
    assert [e[0] for e in events] == ["record", "pip", "reload"]
    assert view.stage == "loaded" and (tmp_path / _ext().filename).read_text() == source


async def test_failed_pip_does_not_load(tmp_path, monkeypatch):
    events = []

    async def fake_install(packages):
        return deps.PipResult(False, packages, "pip", ["ERROR: no matching distribution"], "pip exited with code 1")

    monkeypatch.setattr("zdbf.marketplace.cog.install_packages", fake_install)
    source = "import zz_needed_pkg\nasync def setup(bot):\n    pass\n"
    view = InstallView(_cog(tmp_path, events), _ext(), source, safety_scan(source), author_id=1)
    await view._install_and_load(FakeInteraction())
    assert ("reload", "demo") not in events and not any(e[0] == "reload" for e in events)
    assert view.stage == "installed" and "not loaded" in (view.result or "")


async def test_auto_install_disabled_skips_pip(tmp_path, monkeypatch):
    events = []

    async def fake_install(packages):
        events.append(("pip", tuple(packages)))
        return deps.PipResult(True, packages)

    monkeypatch.setattr("zdbf.marketplace.cog.install_packages", fake_install)
    source = "import zz_needed_pkg\nasync def setup(bot):\n    pass\n"
    view = InstallView(_cog(tmp_path, events, auto=False), _ext(), source, safety_scan(source), author_id=1)
    view.build()
    assert "Install only" in _labels(view)
    await view._install_and_load(FakeInteraction())
    assert not any(e[0] == "pip" for e in events) and any(e[0] == "reload" for e in events)


async def test_non_owner_cannot_install(tmp_path):
    events = []
    source = "import zz_needed_pkg\nasync def setup(bot):\n    pass\n"
    view = InstallView(_cog(tmp_path, events, owner=False), _ext(), source, safety_scan(source), author_id=1)
    inter = FakeInteraction()
    await view._install_and_load(inter)
    assert not events and not (tmp_path / _ext().filename).exists() and inter.sent


@pytest.mark.parametrize("text", ["No module named 'yaml'", "ModuleNotFoundError: No module named 'PIL.Image'"])
def test_missing_re_maps_to_pip_name(text, monkeypatch):
    monkeypatch.setattr(deps, "missing_module", lambda m: True)
    assert deps.packages_for(deps.MISSING_RE.findall(text))[0] in {"PyYAML", "Pillow"}
