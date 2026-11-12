# ZSync Marketplace client - Copyright (c) 2025-2026 TheHolyOneZ (TheZ). All rights reserved.
# Licensed under the ZSync Marketplace License (LICENSE-MARKETPLACE), NOT the Apache License.
# The names ZSync, ZDBF, Zoryx, TheHolyOneZ and TheZ must not be removed or altered.
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import logging
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("zdbf.marketplace")

PIP_NAMES = {
    "cv2": "opencv-python", "PIL": "Pillow", "yaml": "PyYAML", "dotenv": "python-dotenv", "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "Crypto": "pycryptodome", "googleapiclient":
    "google-api-python-client", "google.generativeai": "google-generativeai", "nacl": "PyNaCl", "magic": "python-magic",
    "jwt": "PyJWT", "serial": "pyserial", "usb": "pyusb", "wx": "wxPython", "socks": "PySocks", "chat_exporter":
    "chat-exporter", "yt_dlp": "yt-dlp", "OpenSSL": "pyOpenSSL", "skimage": "scikit-image", "attr": "attrs",
    "docx": "python-docx", "pptx": "python-pptx", "fitz": "PyMuPDF",
}
NEVER_INSTALL = {"discord", "zdbf", "extensions", "atomic_file_system"}
MISSING_RE = re.compile(r"No module named '([\w.]+)'")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")
PIP_TIMEOUT = 600

_lock = asyncio.Lock()


@dataclass(slots=True)
class PipResult:
    ok: bool
    packages: list[str]
    tool: str = "pip"
    output: list[str] = field(default_factory=list)
    error: str | None = None


def missing_module(name: str) -> bool:
    top = name.split(".")[0]
    if not top or top in sys.stdlib_module_names or top in NEVER_INSTALL:
        return False
    try:
        return importlib.util.find_spec(top) is None
    except (ImportError, ValueError):
        return True


def pip_name(module: str) -> str:
    return PIP_NAMES.get(module, PIP_NAMES.get(module.split(".")[0], module.split(".")[0]))


def packages_for(modules: Any, *, skip: set[str] | None = None) -> list[str]:
    skip = skip or set()
    found = {pip_name(m) for m in modules if m.split(".")[0] not in skip and missing_module(m)}
    return sorted(p for p in found if PACKAGE_RE.match(p))


def required_packages(scan: dict[str, Any], *, own_module: str = "") -> list[str]:
    optional = set(scan.get("optional_imports", []))
    needed = [m for m in scan.get("imports", []) if m not in optional]
    return packages_for(needed, skip={own_module} if own_module else None)


def _has_pip() -> bool:
    try:
        return importlib.util.find_spec("pip") is not None
    except (ImportError, ValueError):
        return False


def install_command(packages: list[str]) -> tuple[str, list[str]] | None:
    if _has_pip():
        return "pip", [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *packages]
    uv = shutil.which("uv")
    if uv:
        return "uv", [uv, "pip", "install", "--python", sys.executable, *packages]
    return None


def describe_command(packages: list[str]) -> str:
    cmd = install_command(packages)
    if cmd is None:
        return "no installer found (pip or uv)"
    tool, args = cmd
    shown = [Path(args[0]).name, *args[1:]]
    if tool == "uv":
        shown[shown.index("--python") + 1] = Path(sys.executable).name
    return " ".join(shown)


async def install_packages(packages: list[str], *, timeout: float = PIP_TIMEOUT) -> PipResult:
    bad = [p for p in packages if not PACKAGE_RE.match(p)]
    if bad:
        return PipResult(False, packages, error=f"refusing unusual package names: {', '.join(bad)}")
    if not packages:
        return PipResult(True, [])
    cmd = install_command(packages)
    if cmd is None:
        return PipResult(False, packages, tool="none",
                         error="Neither pip nor uv is available for this Python. Install pip "
                               f"(`{Path(sys.executable).name} -m ensurepip`) and try again.")
    tool, args = cmd
    async with _lock:
        log.info("installing packages with %s: %s", tool, " ".join(packages))
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return PipResult(False, packages, tool, error=f"{tool} took longer than {timeout / 60:.0f} minutes")
    importlib.invalidate_caches()
    lines = out.decode(errors="ignore").strip().splitlines()
    ok = proc.returncode == 0
    if ok:
        log.info("installed %s", " ".join(packages))
    else:
        log.warning("%s failed (exit %s) for %s", tool, proc.returncode, " ".join(packages))
    return PipResult(ok, packages, tool, lines[-8:], None if ok else f"{tool} exited with code {proc.returncode}")
