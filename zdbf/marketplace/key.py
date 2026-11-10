# ZSync Marketplace client - Copyright (c) 2025-2026 TheHolyOneZ (TheZ). All rights reserved.
# Licensed under the ZSync Marketplace License (LICENSE-MARKETPLACE), NOT the Apache License.
# The names ZSync, ZDBF, Zoryx, TheHolyOneZ and TheZ must not be removed or altered.
from __future__ import annotations

import logging
import secrets
import string
from pathlib import Path

from ..core.storage import global_file_handler

log = logging.getLogger("zdbf.marketplace")

DATA_DIR = Path("data/marketplace")
KEY_FILE = DATA_DIR / "zsync-zdbf-key.txt"
LEGACY_FILES = (DATA_DIR / "ZygnalID.txt", Path("data/ZygnalID.txt"))
ALPHABET = string.ascii_letters + string.digits
KEY_LENGTH = 16

__all__ = ["KEY_FILE", "ensure_key", "is_valid_key"]


def is_valid_key(value: str) -> bool:
    return len(value) == KEY_LENGTH and all(c in ALPHABET for c in value)


async def ensure_key() -> tuple[str, str]:
    current = (await global_file_handler.atomic_read(KEY_FILE, use_cache=False) or "").strip()
    if is_valid_key(current):
        return current, "existing"
    for legacy in LEGACY_FILES:
        old = (await global_file_handler.atomic_read(legacy, use_cache=False) or "").strip()
        if is_valid_key(old):
            await global_file_handler.atomic_write(KEY_FILE, old)
            log.info("migrated legacy ZygnalID from %s to %s", legacy, KEY_FILE)
            return old, "migrated"
    key = "".join(secrets.choice(ALPHABET) for _ in range(KEY_LENGTH))
    await global_file_handler.atomic_write(KEY_FILE, key)
    log.info("generated a new ZSync ZDBF Key (needs activation before downloads work)")
    return key, "generated"
