# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Sequence
from pathlib import Path

__all__ = ["Sandbox", "SandboxError"]

DENIED_NAMES = (
    ".env", ".env.*", "*.db", "*.db-wal", "*.db-shm", "*.sqlite", "*.sqlite3", "*.pem", "*.key",
    ".git", ".local", ".venv", "venv", ".ssh", "zsync-zdbf-key.txt", "ZygnalID.txt", "link.json",
)
DENIED_DIRS = ("data/dashboard", "data/marketplace", "data/db_backups", ".git", ".local", ".venv")
_DRIVE = re.compile(r"^[A-Za-z]:")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_PATH = 1024


class SandboxError(Exception):
    pass


class Sandbox:
    def __init__(self, base: str | os.PathLike[str], roots: Sequence[str], *, max_bytes: int) -> None:
        self.base = Path(os.path.realpath(base))
        self.roots = [tuple(Path(r).parts) for r in roots if r.strip()]
        self.max_bytes = max_bytes
        self._denied_dirs = [Path(os.path.realpath(self.base.joinpath(d))) for d in DENIED_DIRS]

    def root_names(self) -> list[str]:
        return ["/".join(r) for r in self.roots]

    @staticmethod
    def _split(rel: str) -> list[str]:
        if not isinstance(rel, str) or not rel.strip() or len(rel) > MAX_PATH:
            raise SandboxError("invalid path")
        if _CONTROL.search(rel):
            raise SandboxError("the path contains control characters")
        norm = rel.replace("\\", "/")
        if norm.startswith("/") or _DRIVE.match(norm):
            raise SandboxError("absolute paths are not allowed")
        parts = [p for p in norm.split("/") if p not in ("", ".")]
        if not parts:
            raise SandboxError("invalid path")
        if ".." in parts:
            raise SandboxError("'..' is not allowed in a path")
        return parts

    @staticmethod
    def _name_denied(name: str) -> bool:
        lowered = name.lower()
        return any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in DENIED_NAMES)

    def _inside(self, path: Path, parent: Path) -> bool:
        return path == parent or parent in path.parents

    def resolve(self, rel: str) -> Path:
        parts = self._split(rel)
        root = next((r for r in self.roots if tuple(parts[:len(r)]) == r), None)
        if root is None:
            raise SandboxError("that path is outside the folders the dashboard may open")
        root_real = Path(os.path.realpath(self.base.joinpath(*root)))
        if not self._inside(root_real, self.base):
            raise SandboxError("that folder is outside the bot directory")
        real = Path(os.path.realpath(self.base.joinpath(*parts)))
        if not self._inside(real, root_real):
            raise SandboxError("that path leaves its folder through a link")
        inner = real.relative_to(self.base).parts
        if any(self._name_denied(p) for p in parts) or any(self._name_denied(p) for p in inner):
            raise SandboxError("that file is protected and cannot be opened from the dashboard")
        if any(self._inside(real, d) for d in self._denied_dirs):
            raise SandboxError("that folder is protected and cannot be opened from the dashboard")
        return real

    def relative(self, path: Path) -> str:
        return Path(os.path.realpath(path)).relative_to(self.base).as_posix()

    def check_size(self, size: int) -> None:
        if size > self.max_bytes:
            raise SandboxError(f"the file is larger than the limit of {self.max_bytes // 1024} KB")

    def visible(self, path: Path) -> bool:
        if path.name == "__pycache__" or self._name_denied(path.name):
            return False
        real = Path(os.path.realpath(path))
        if not any(self._inside(real, Path(os.path.realpath(self.base.joinpath(*r)))) for r in self.roots):
            return False
        return not any(self._inside(real, d) for d in self._denied_dirs)
