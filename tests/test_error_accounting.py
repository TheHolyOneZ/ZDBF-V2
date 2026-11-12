# SPDX-License-Identifier: Apache-2.0
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord.ext import commands

from zdbf.cogs.diagnostics import Diagnostics
from zdbf.cogs.help import Category, HelpView
from zdbf.core.errors import handle_command_error
from zdbf.core.metrics import MetricsCollector


def _ctx(bot):
    command = SimpleNamespace(qualified_name="ping", signature="", has_error_handler=lambda: False)
    return SimpleNamespace(bot=bot, command=command, cog=None, clean_prefix="!", interaction=None,
                           author=SimpleNamespace(id=5), guild=SimpleNamespace(id=10), send=AsyncMock())


def _bot():
    return SimpleNamespace(metrics=MetricsCollector(), alerts=SimpleNamespace(send=AsyncMock()))


async def test_refused_commands_are_not_errors():
    bot = _bot()
    cooldown = commands.CommandOnCooldown(commands.Cooldown(1, 5), 3.0, commands.BucketType.user)
    for error in (cooldown, commands.MissingPermissions(["manage_guild"]), commands.BadArgument("no")):
        await handle_command_error(bot, _ctx(bot), error)
    assert bot.metrics.errors_total == 0
    assert bot.metrics.rejections_total == 3
    assert bot.metrics.rejection_reasons["CommandOnCooldown"] == 1
    assert not bot.alerts.send.await_count


async def test_crashes_are_errors_with_an_alert():
    bot = _bot()
    await handle_command_error(bot, _ctx(bot), commands.CommandInvokeError(ValueError("boom")))
    assert bot.metrics.errors_total == 1
    assert bot.metrics.rejections_total == 0
    assert "ValueError: boom" in bot.metrics.recent_errors[0].error
    bot.alerts.send.assert_awaited_once()


def _diagnostics(tmp_path, monkeypatch, commands_run: int, crashed: int, min_commands: int = 20):
    monkeypatch.chdir(tmp_path)
    metrics = MetricsCollector()
    for _ in range(commands_run):
        metrics.record_command("ping")
    for _ in range(crashed):
        metrics.record_error("ping", "ValueError: boom")
    settings = SimpleNamespace(loop_lag_threshold_ms=500, health_interval_minutes=5, error_rate_warn_percent=10.0,
                               error_rate_min_commands=min_commands)
    bot = SimpleNamespace(metrics=metrics, latency=0.05, alerts=SimpleNamespace(send=AsyncMock()),
                          db=SimpleNamespace(kv_set=AsyncMock()),
                          config=SimpleNamespace(settings=SimpleNamespace(diagnostics=settings)))
    cog = Diagnostics(bot)
    cog.report = lambda: {}
    return cog, bot


@pytest.mark.parametrize(("commands_run", "crashed", "status"), [
    (7, 1, "healthy"),
    (19, 5, "healthy"),
    (40, 2, "healthy"),
    (40, 5, "degraded"),
    (40, 9, "critical"),
])
async def test_health_needs_enough_commands(tmp_path, monkeypatch, commands_run, crashed, status):
    cog, bot = _diagnostics(tmp_path, monkeypatch, commands_run, crashed)
    snap = await cog.health_check()
    assert snap.status == status
    assert bot.alerts.send.await_count == (status != "healthy")
    if status != "healthy":
        assert f"{crashed} of {commands_run} commands crashed" in bot.alerts.send.await_args.args[1]


def _help(modules_off):
    bot = SimpleNamespace(
        user=SimpleNamespace(display_name="Bot", display_avatar=SimpleNamespace(url="https://e.com/a.png"), id=1),
        config=SimpleNamespace(settings=SimpleNamespace(ui=SimpleNamespace(
            help_banner="", support_url="", invite_button=False, invite_permissions=8))),
        legacy_aliases={}, slash_guard=SimpleNamespace(demoted={}),
        application=SimpleNamespace(description="", bot_public=False), application_id=1)
    return HelpView(bot, 1, [Category("General", "", [])], "!", modules_off=modules_off)


def _texts(view):
    return "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))


async def test_help_names_switched_off_modules_for_owners():
    view = _help(["dashboard", "cluster"])
    view.build()
    assert "Switched off: `dashboard`, `cluster`" in _texts(view)
    view.search("dashboard export")
    view.build()
    assert "`dashboard` module is switched off" in _texts(view)
    assert "/fw modules module:dashboard enabled:true" in _texts(view)


async def test_help_without_switched_off_modules_says_nothing_extra():
    view = _help([])
    view.build()
    assert "Switched off" not in _texts(view)
    view.search("dashboard")
    view.build()
    assert "Nothing matches" in _texts(view)
