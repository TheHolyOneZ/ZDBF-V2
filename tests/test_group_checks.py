# SPDX-License-Identifier: Apache-2.0
import asyncio
from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands
from discord.ext.commands.view import StringView

from zdbf.core.bot import ZDBFBot
from zdbf.core.config import Config
from zdbf.core.permissions import OwnerOnly, is_owner_only, owner_only, parent_checks

OWNER, STRANGER = 1, 999


def _ctx(bot, command, author_id):
    message = SimpleNamespace(content=f"!{command.qualified_name}", _state=None, attachments=[],
                              author=SimpleNamespace(id=author_id, bot=False),
                              guild=SimpleNamespace(id=10, owner_id=2), channel=SimpleNamespace(id=20))
    ctx = commands.Context(prefix="!", view=StringView(message.content), bot=bot, message=message)
    ctx.command = command
    return ctx


@pytest.fixture
async def bot(tmp_cwd):
    config = Config().load()
    config.settings.modules.cluster = False
    instance = ZDBFBot(config)
    await instance.__aenter__()
    try:
        await instance.db.connect()
        await instance.plugins.load_settings()
        await instance.ext.load_builtin()
        instance._app_owner_ids = {OWNER}
        yield instance
    finally:
        await instance.close()


async def test_every_owner_command_refuses_a_stranger(bot):
    protected = [c for c in bot.walk_commands() if is_owner_only(c)]
    names = {c.qualified_name for c in protected}
    assert len(protected) > 30
    assert {"fw shutdown", "fw config set", "ext load", "ext unload", "diag migrate", "shard reset",
            "eventhooks disable"} <= names
    for command in protected:
        with pytest.raises(commands.CheckFailure):
            await command.can_run(_ctx(bot, command, STRANGER))
    for name in ("fw shutdown", "ext load", "eventhooks disable"):
        command = bot.get_command(name)
        with pytest.raises(OwnerOnly):
            await command.can_run(_ctx(bot, command, STRANGER))


async def test_owner_still_passes_group_checks(bot):
    for name in ("fw", "fw cache", "fw config set", "ext load", "diag overview", "eventhooks list"):
        command = bot.get_command(name)
        assert await command.can_run(_ctx(bot, command, OWNER)), name


async def test_open_commands_stay_open(bot):
    for name in ("ping", "help", "about", "stats"):
        command = bot.get_command(name)
        assert await command.can_run(_ctx(bot, command, STRANGER)), name


async def test_invoking_a_subcommand_runs_the_group_check():
    ran = []

    @commands.group(name="vault", invoke_without_command=True)
    @owner_only()
    async def vault(ctx):
        ran.append("vault")

    @vault.group(name="keys", invoke_without_command=True)
    async def keys(ctx):
        ran.append("keys")

    @keys.command(name="wipe")
    async def wipe(ctx):
        ran.append("wipe")

    owners = {OWNER}

    async def is_owner(user):
        return user.id in owners

    errors = []

    async def on_command_error(ctx, error):
        errors.append(error)

    for guarded in (False, True):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none(), help_command=None)
        bot.is_owner = is_owner
        bot.on_command_error = on_command_error
        if guarded:
            bot.add_check(parent_checks)
        bot.add_command(vault)
        async with bot:
            for author in (STRANGER, OWNER):
                ran.clear()
                errors.clear()
                message = SimpleNamespace(content="!vault keys wipe", _state=None, attachments=[], guild=None,
                                          author=SimpleNamespace(id=author, bot=False), channel=SimpleNamespace(id=1))
                ctx = commands.Context(prefix="!", view=StringView(message.content), bot=bot, message=message)
                ctx.view.skip_string("!")
                ctx.invoked_with = ctx.view.get_word()
                ctx.command = bot.all_commands[ctx.invoked_with]
                await bot.invoke(ctx)
                await asyncio.sleep(0.01)
                refused = guarded and author == STRANGER
                assert ran == ([] if refused else ["wipe"]), (guarded, author)
                assert [type(e) for e in errors] == ([OwnerOnly] if refused else [])
        bot.remove_command("vault")


async def test_slash_subcommands_run_the_group_check_too(bot):
    for name in ("fw shutdown", "ext load", "diag migrate", "eventhooks disable"):
        command = bot.get_command(name)
        slash = command.app_command
        assert slash is not None, name
        stranger = SimpleNamespace(client=bot, _baton=_ctx(bot, command, STRANGER))
        with pytest.raises(OwnerOnly):
            await slash._check_can_run(stranger)
        owner = SimpleNamespace(client=bot, _baton=_ctx(bot, command, OWNER))
        assert await slash._check_can_run(owner), name
    ping = bot.get_command("ping")
    assert await ping.app_command._check_can_run(SimpleNamespace(client=bot, _baton=_ctx(bot, ping, STRANGER)))
