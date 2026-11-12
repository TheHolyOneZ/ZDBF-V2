# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import secrets
import zipfile
from pathlib import Path

__all__ = ["ARCHIVE_ROOT", "build_archive", "new_setup_key", "web_root"]

ARCHIVE_ROOT = "zdbf-dashboard"
KEY_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
KEY_FILE = "data/setup-key.php"
KEY_TEMPLATE = "<?php\nif (!defined('ZDBF_DASHBOARD')) {{\n    http_response_code(404);\n    exit;\n}}\nreturn '{key}';\n"
KEEP_HIDDEN = {".htaccess"}
SKIP_DIRS = {"__pycache__", "node_modules", ".git"}


def web_root() -> Path | None:
    root = Path(__file__).resolve().parents[3] / "dashboard"
    return root if (root / "index.php").is_file() else None


def _wanted(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    if path.name.startswith(".") and path.name not in KEEP_HIDDEN:
        return False
    return not (rel.parts[0] == "data" and path.name not in KEEP_HIDDEN)


def new_setup_key() -> str:
    raw = "".join(secrets.choice(KEY_ALPHABET) for _ in range(16))
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def build_archive(target: Path, setup_key: str) -> tuple[int, int]:
    root = web_root()
    if root is None:
        raise FileNotFoundError("the dashboard folder is missing from this ZDBF installation")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    count = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink() and _wanted(root, path):
                archive.write(path, f"{ARCHIVE_ROOT}/{path.relative_to(root).as_posix()}")
                count += 1
        archive.writestr(f"{ARCHIVE_ROOT}/{KEY_FILE}", KEY_TEMPLATE.format(key=setup_key))
        count += 1
    tmp.replace(target)
    return count, target.stat().st_size
