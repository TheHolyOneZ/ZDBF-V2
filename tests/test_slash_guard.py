# SPDX-License-Identifier: Apache-2.0
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord import app_commands
from discord.ext import commands

from zdbf.core.slash_guard import GuardedTree, SlashGuard, run_app_command


def _app(name: str, module: str) -> app_commands.Command:
    async def cb(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(name)

    cmd = app_commands.Command(name=name, description="test", callback=cb)
    cmd.module = module
    return cmd


def _bot() -> commands.Bot:
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none(), tree_cls=GuardedTree)
    bot.slash_guard = SlashGuard(bot)  # type: ignore[attr-defined]
    return bot


async def test_framework_first_and_fallbacks():
    bot = _bot()
    for i in range(95):
        bot.tree.add_command(_app(f"core{i}", "zdbf.cogs.fake"))
    for i in range(10):
        bot.tree.add_command(_app(f"ext{i}", __name__))

    @commands.hybrid_command(name="hybridx", description="hybrid")
    async def hybridx(ctx):
        await ctx.send("hybrid")

    hybridx.app_command.module = __name__
    bot.add_command(hybridx)
    guard: SlashGuard = bot.slash_guard  # type: ignore[attr-defined]
    assert len(bot.tree.get_commands()) == 100 and len(guard.demoted) == 6
    late = _app("corelate", "zdbf.cogs.fake")
    guard._stash[("global", "corelate")] = late
    demoted = guard.enforce([None])
    assert bot.tree.get_command("corelate") is not None
    demoted = guard.enforce([None])
    names = {d.name for d in demoted}
    assert len(bot.tree.get_commands()) == 100
    assert all(bot.tree.get_command(f"core{i}") for i in range(95))
    assert len(names) == 7 and guard.newly_demoted
    assert all(d.fallback for d in demoted)
    for d in demoted:
        if d.kind == "app":
            assert bot.get_command(d.name).extras.get("zdbf_slash_fallback")
    assert bot.get_command("hybridx") is hybridx or "hybridx" not in names

    for i in range(11):
        bot.tree.remove_command(f"core{i}")
    guard._stash.pop(("global", "corelate"), None)
    bot.tree.remove_command("corelate")
    assert guard.enforce([None]) == []
    assert all(bot.tree.get_command(f"ext{i}") for i in range(10))
    assert not any(c.extras.get("zdbf_slash_fallback") for c in bot.commands)


async def test_prefix_adapter_converts_arguments():
    seen = {}

    @app_commands.command(name="add", description="add")
    @app_commands.describe(a="first")
    async def add(interaction: discord.Interaction, a: int, flag: bool, text: str) -> None:
        seen.update(a=a, flag=flag, text=text, namespace=interaction.namespace.a)
        await interaction.response.defer()
        await interaction.followup.send(f"{a} {text}")

    ctx = SimpleNamespace(send=AsyncMock(), typing=AsyncMock(), guild=None, author=SimpleNamespace(id=1),
                          channel=SimpleNamespace(id=2), message=SimpleNamespace(id=3, created_at=None, attachments=[]),
                          bot=SimpleNamespace(is_owner=AsyncMock(return_value=False)), clean_prefix="!")
    await run_app_command(ctx, add, '5 yes "hello there" world')
    assert seen == {"a": 5, "flag": True, "text": "hello there world", "namespace": 5}
    ctx.send.assert_awaited_with("5 hello there world")

    group = app_commands.Group(name="grp", description="g")
    group.add_command(add)
    ctx.send.reset_mock()
    await run_app_command(ctx, group, "")
    assert "subcommands" in ctx.send.await_args.args[0]
    await run_app_command(ctx, group, "add 1 no x")
    assert seen["a"] == 1 and seen["flag"] is False
