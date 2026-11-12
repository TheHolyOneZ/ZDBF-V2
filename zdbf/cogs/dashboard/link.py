# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ...core.storage import write_bytes_durable

__all__ = ["DATA_DIR", "Link", "LinkStore"]

DATA_DIR = Path("data/dashboard")


@dataclass(slots=True)
class Link:
    url: str
    install_id: str
    secret: str
    bot_id: str
    paired_at: float = field(default_factory=time.time)

    def endpoint(self, path: str) -> str:
        return f"{self.url}/{path}"


class LinkStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_DIR / "link.json"

    def load(self) -> Link | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return Link(**{k: raw[k] for k in Link.__dataclass_fields__ if k in raw})
        except (FileNotFoundError, ValueError, TypeError):
            return None

    def save(self, link: Link) -> None:
        write_bytes_durable(self.path, json.dumps(asdict(link), indent=2).encode())
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)

    def delete(self) -> bool:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        return True
