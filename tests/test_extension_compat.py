# SPDX-License-Identifier: Apache-2.0
import sys
import textwrap

import discord
import pytest
from discord.ext import commands

from zdbf.core.bot import ZDBFBot
from zdbf.core.extensions import SetupShim, accept_old_setup

COG = """
from discord.ext import commands


class Probe(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def probe(self, ctx):
        await ctx.send("ok")

"""
SETUPS = {
    "returns_cog_after_create_task": """
        import asyncio

        def setup(bot):
            cog = Probe(bot)
            asyncio.get_event_loop().create_task(bot.add_cog(cog))
            return cog
    """,
    "never_awaits_add_cog": """
        def setup(bot):
            bot.add_cog(Probe(bot))
    """,
    "returns_the_coroutine": """
        def setup(bot):
            return bot.add_cog(Probe(bot))
    """,
    "modern": """
        async def setup(bot):
            await bot.add_cog(Probe(bot))
    """,
}


class Bot(commands.Bot):
    async def _load_from_module_spec(self, spec, key):
        accept_old_setup(spec, key)
        await super()._load_from_module_spec(spec, key)


@pytest.fixture
def package(tmp_path, monkeypatch):
    folder = tmp_path / "compat_ext"
    folder.mkdir()
    (folder / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    yield folder
    for name in [n for n in sys.modules if n.startswith("compat_ext")]:
        del sys.modules[name]


@pytest.mark.parametrize("style", sorted(SETUPS))
async def test_every_setup_style_adds_its_cog(package, style):
    (package / f"{style}.py").write_text(COG + textwrap.dedent(SETUPS[style]))
    bot = Bot(command_prefix="!", intents=discord.Intents.none())
    await bot.load_extension(f"compat_ext.{style}")
    assert bot.get_cog("Probe") is not None and bot.get_command("probe") is not None
    assert "add_cog" not in vars(bot)
    await bot.unload_extension(f"compat_ext.{style}")
    assert bot.get_cog("Probe") is None
    await bot.close()


async def test_a_failing_old_style_setup_reports_the_real_error(package):
    (package / "broken.py").write_text(COG + textwrap.dedent("""
        def setup(bot):
            bot.add_cog(Probe(bot))
            bot.add_cog(Probe(bot))
    """))
    bot = Bot(command_prefix="!", intents=discord.Intents.none())
    with pytest.raises(commands.ExtensionFailed) as caught:
        await bot.load_extension("compat_ext.broken")
    assert isinstance(caught.value.original, discord.ClientException)
    assert bot.get_cog("Probe") is None and "add_cog" not in vars(bot)
    await bot.close()


def test_the_bot_hooks_into_the_loader_and_skips_its_own_modules():
    from types import SimpleNamespace

    assert hasattr(commands.bot.BotBase, "_load_from_module_spec")
    assert ZDBFBot._load_from_module_spec is not commands.bot.BotBase._load_from_module_spec
    loader = object()
    builtin = SimpleNamespace(loader=loader)
    accept_old_setup(builtin, "zdbf.cogs.core")
    assert builtin.loader is loader
    user = SimpleNamespace(loader=loader)
    accept_old_setup(user, "extensions.memes")
    accept_old_setup(user, "extensions.memes")
    assert isinstance(user.loader, SetupShim) and user.loader._loader is loader
