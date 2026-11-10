# SPDX-License-Identifier: Apache-2.0
from types import SimpleNamespace
from typing import Literal

from discord import app_commands
from discord.ext import commands

from zdbf.cogs.help import Category, HelpView, make_entry, options_of, usage_lines
from zdbf.ui.cards import MAX_COMPONENTS, MAX_TEXT


def _bot():
    ui = SimpleNamespace(help_banner="", support_url="https://discord.gg/example", invite_button=True,
                         invite_permissions=8)
    cooldowns = SimpleNamespace(default_rate=3, default_per=5.0)
    return SimpleNamespace(
        user=SimpleNamespace(display_name="Test Bot", display_avatar=SimpleNamespace(url="https://e.com/a.png"), id=1),
        config=SimpleNamespace(settings=SimpleNamespace(ui=ui, cooldowns=cooldowns)),
        legacy_aliases={"backupcreate": "backup create"},
        slash_guard=SimpleNamespace(demoted={}),
        application=SimpleNamespace(description="A very good bot. " * 40, bot_public=True), application_id=1)


@commands.hybrid_group(name="backup", description="Backups")
async def backup(ctx):
    pass


@backup.command(name="create", description="Create a backup of this server")
@app_commands.describe(label="A name for the backup", mode="What to include")
async def backup_create(ctx, label: str, mode: Literal["full", "roles"] = "full", pin: bool = False):
    pass


def _fits(view, label):
    assert view.content_length() <= MAX_TEXT, f"{label}: {view.content_length()} chars"
    assert view.total_children_count <= MAX_COMPONENTS, f"{label}: {view.total_children_count} components"


def test_options_and_usage():
    entry = make_entry(_bot(), backup_create)
    options = options_of(backup_create)
    assert [(o.name, o.kind, o.required) for o in options] == [
        ("label", "text", True), ("mode", "choice", False), ("pin", "yes / no", False)]
    assert options[0].description == "A name for the backup"
    assert options[1].choices == ("full", "roles") and options[1].default == "full"
    assert usage_lines(entry, options, "!") == ["/backup create label:<text> [mode] [pin]",
                                                "!backup create <label> [mode] [pin]"]


async def test_every_page_fits_with_huge_data():
    bot = _bot()
    cats = []
    for c in range(40):
        entries = []
        for i in range(60):
            cmd = commands.Command(backup_create.callback, name=f"cmd{c}x{i}", description="d" * 400)
            entries.append(make_entry(bot, cmd))
        cats.append(Category(f"Category {c} " + "x" * 80, "y" * 400, entries))
    view = HelpView(bot, 1, cats, "!", banner="https://e.com/banner.png")
    for page in range(8):
        view.home_page = page
        view.build()
        _fits(view, f"home {page}")
    view.mode, view.category = "category", cats[0]
    for page in range(10):
        view.page = page
        view.build()
        _fits(view, f"category {page}")
    view.open_command(backup)
    view.build()
    _fits(view, "group detail")
    view.open_command(backup_create)
    view.build()
    _fits(view, "command detail")
    view.search("cmd1")
    view.build()
    _fits(view, "search")
    assert view.results and view.results[0].slash_name.startswith("cmd1")


async def test_search_finds_v1_names_and_back_navigation():
    bot = _bot()
    cats = [Category("Backup", "Backups", [make_entry(bot, backup_create)])]
    view = HelpView(bot, 1, cats, "!")
    view.search("backupcreate")
    assert [e.prefix_name for e in view.results] == ["backup create"]
    view.open_command(backup_create)
    assert view.mode == "command"
    view._restore(view.history.pop())
    assert view.mode == "search"


async def test_default_cooldown_applies_only_without_own_cooldown():
    from unittest.mock import AsyncMock

    import pytest

    from zdbf.core.bot import ZDBFBot

    fake = SimpleNamespace(is_owner=AsyncMock(return_value=False), _cooldown_maps={},
                           config=SimpleNamespace(settings=SimpleNamespace(
                               cooldowns=SimpleNamespace(default_rate=2, default_per=60.0))))
    plain = commands.Command(backup_create.callback, name="plain")
    ctx = SimpleNamespace(command=plain, author=SimpleNamespace(id=5), message=SimpleNamespace(author=SimpleNamespace(id=5)))
    assert await ZDBFBot._default_cooldown(fake, ctx)
    assert await ZDBFBot._default_cooldown(fake, ctx)
    with pytest.raises(commands.CommandOnCooldown):
        await ZDBFBot._default_cooldown(fake, ctx)
    own = commands.cooldown(10, 1)(commands.Command(backup_create.callback, name="own"))
    ctx.command = own
    for _ in range(5):
        assert await ZDBFBot._default_cooldown(fake, ctx)
    fake.is_owner = AsyncMock(return_value=True)
    ctx.command = plain
    assert await ZDBFBot._default_cooldown(fake, ctx)
