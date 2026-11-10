# SPDX-License-Identifier: Apache-2.0
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord


async def test_limits_allow_first_use_right_after_boot(monkeypatch):
    import time

    from zdbf.cogs.automations.templates import Runtime
    from zdbf.core.alerts import AlertManager

    monkeypatch.setattr(time, "monotonic", lambda: 5.0)
    runtime = Runtime(SimpleNamespace(bot=None))
    assert runtime.throttle("cooldown", 60)
    assert not runtime.throttle("cooldown", 60)

    channel = AsyncMock(spec=discord.TextChannel)
    bot = SimpleNamespace(get_channel=lambda _id: channel)
    alerts = AlertManager(bot)  # type: ignore[arg-type]
    alerts.channels = {"default": 1}
    assert await alerts.send("test", "first alert after boot", "warning")
    channel.send.assert_awaited_once()
