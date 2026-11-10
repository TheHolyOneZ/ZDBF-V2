# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from .config import LoggingSettings

__all__ = ["cleanup_old_logs", "setup_logging"]

_FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(settings: LoggingSettings) -> Path:
    log_dir = Path(settings.directory)
    log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, settings.level, logging.INFO)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.DEBUG)

    console = RichHandler(
        console=Console(stderr=True),
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        markup=False,
        log_time_format="[%H:%M:%S]",
    )
    console.setLevel(level)
    root.addHandler(console)

    main_file = logging.handlers.RotatingFileHandler(
        log_dir / "zdbf.log",
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    main_file.setLevel(logging.DEBUG if level <= logging.DEBUG else logging.INFO)
    main_file.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(main_file)

    error_file = logging.handlers.RotatingFileHandler(
        log_dir / "errors.log",
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(error_file)

    logging.getLogger("discord").setLevel(level if level > logging.DEBUG else logging.INFO)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    return log_dir


def cleanup_old_logs(directory: str | Path, days: int) -> int:
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for path in Path(directory).glob("*.log.*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
