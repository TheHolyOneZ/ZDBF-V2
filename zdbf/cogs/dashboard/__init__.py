# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...core.bot import ZDBFBot


async def setup(bot: ZDBFBot) -> None:
    from .cog import Dashboard

    await bot.add_cog(Dashboard(bot))
