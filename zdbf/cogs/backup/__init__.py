# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from typing import TYPE_CHECKING

from .cog import Backup

if TYPE_CHECKING:
    from ...core.bot import ZDBFBot

__all__ = ["Backup"]


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(Backup(bot))
