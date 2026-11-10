# SPDX-License-Identifier: Apache-2.0
import re
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from zdbf.ui import cards
from zdbf.ui.cards import MAX_COMPONENTS, MAX_TEXT

ROOT = Path(__file__).resolve().parents[1]


def assert_fits(view: discord.ui.LayoutView, label: str) -> None:
    assert view.content_length() <= MAX_TEXT, f"{label}: {view.content_length()} characters"
    assert view.total_children_count <= MAX_COMPONENTS, f"{label}: {view.total_children_count} components"


def walk_list_detail(view, label: str) -> int:
    view.build()
    pages = 0
    while True:
        view.build()
        assert_fits(view, f"{label} page {view.page + 1}")
        pages += 1
        before = view.page
        view.page += 1
        view.build()
        if view.page == before or view.page < before or pages > 500:
            break
    view.page = 0
    while view.picker.page + 1 < view.picker.pages:
        view.picker.page += 1
        view.build()
        assert_fits(view, f"{label} select page {view.picker.page + 1}")
    view.selected = view.items[0]
    view.build()
    assert_fits(view, f"{label} detail")
    return pages


def _guild():
    return SimpleNamespace(name="A server with a long name " * 3, roles=[0] * 250, channels=[0] * 500,
                           emojis=[0] * 100, member_count=100_000, id=1)


async def test_backup_dashboard_600_backups():
    from zdbf.cogs.backup.cog import Dashboard
    from zdbf.cogs.backup.snapshot import BackupEntry

    entries = [BackupEntry(f"{i:012x}", 1, f"Backup label number {i} " * 4, "note " * 50, i % 7 == 0, i % 2 == 0,
                           123456789012345678, "2026-11-10T12:00:00", 10_000_000, "a" * 64, "2",
                           ["roles", "channels"], {"roles": 250, "channels": 500, "members": 100_000}, "x")
               for i in range(600)]
    cog = SimpleNamespace(settings=SimpleNamespace(max_per_guild=1000))
    view = Dashboard(cog, _guild(), entries, author_id=1)
    assert walk_list_detail(view, "backup dashboard") >= 100
    assert view.picker.pages == 24


async def test_plugin_browser_120_plugins():
    from zdbf.cogs.plugins import PluginBrowser
    from zdbf.core.plugins import PluginMetadata

    metas = {}
    for i in range(120):
        m = PluginMetadata(name=f"plugin_with_a_long_name_{i}")
        m.description = "A very long description. " * 40
        m.commands = {f"command{j} sub{j}" for j in range(300)}
        m.dependencies = {f"dep{j}": ">=1.0" for j in range(30)}
        metas[m.name] = m
    plugins = SimpleNamespace(all=lambda: metas, check_dependencies=lambda m: [f"missing {d}" for d in m.dependencies],
                              detect_conflicts=lambda m: [], enforce_dependencies=True, enforce_conflicts=True)
    bot = SimpleNamespace(plugins=plugins)
    view = PluginBrowser(bot, author_id=1)
    assert walk_list_detail(view, "plugin browser") == 15


async def test_shard_monitor_80_shards():
    from zdbf.cogs.shards import MonitorView, ShardMonitor

    bot = SimpleNamespace(config=SimpleNamespace(settings=SimpleNamespace(shards=SimpleNamespace(alert_threshold=3))),
                          guilds=[], latency=0.05, shards={})
    cog = ShardMonitor(bot)  # type: ignore[arg-type]
    for sid in range(80):
        metric = cog.m(sid)
        metric.latencies.extend([1500.0] * 120)
        metric.events.update({f"event_{j}": j for j in range(50)})
        metric.disconnected()
    view = MonitorView(cog, author_id=1)
    assert walk_list_detail(view, "shard monitor") == 6


async def test_permissions_300_rules():
    from zdbf.cogs.settings import PermissionsView

    table = {f"command{i} subcommand{i}": list(range(10**17, 10**17 + 10)) for i in range(300)}
    view = PermissionsView(SimpleNamespace(), _guild(), table, author_id=1)
    for page in range(25):
        view.page = page
        view.build()
        assert_fits(view, f"permissions page {page + 1}")
    while view.remover.page + 1 < view.remover.pages:
        view.remover.page += 1
        view.build()
        assert_fits(view, "permissions remover")


async def test_marketplace_details_20kb():
    from zdbf.marketplace.client import Extension
    from zdbf.marketplace.views import detail_card, detail_pages

    ext = Extension(1, "Huge extension", "d" * 300, ("A long paragraph. " * 40 + "\n\n") * 30, "1.0.0", "someone",
                    "user", "working", "2026-01-01", "- change\n" * 800, "py", "")
    pages = detail_pages(ext)
    assert len(pages) > 5
    for i in range(len(pages)):
        assert_fits(cards.StaticView(detail_card(ext, None, i)), f"marketplace detail page {i + 1}")


async def test_automation_builder_pages():
    from zdbf.cogs.automations.actions import ACTION_TYPES, CUSTOM, TRIGGERS
    from zdbf.cogs.automations.builder import BuilderView

    view = BuilderView(SimpleNamespace(for_guild=lambda _g: []), CUSTOM, author_id=1, guild_id=1)
    for trigger in TRIGGERS:
        view.config["trigger"] = trigger
        view.build()
        assert_fits(view, f"builder {trigger}")
    view.config["actions"] = [{"type": t, **ACTION_TYPES[t].defaults(), "message": "x" * 4000}
                              for t in list(ACTION_TYPES) * 2][:15]
    view.mode = "actions"
    view.build()
    assert_fits(view, "action list")
    for i in range(15):
        view.mode, view.selected = "action", i
        view.build()
        assert_fits(view, f"action {i}")


async def test_safety_net_turns_oversized_cards_into_pages():
    huge = cards.card("Report", *[f"line {i} " + "x" * 200 for i in range(100)], foot="footer")
    view = cards.static(huge)
    assert view.__class__.__name__ == "Paginator"
    assert view.page_count > 1
    for i in range(view.page_count):
        view.index = i
        view.build()
        assert_fits(view, f"safety net page {i + 1}")
    many = cards.static(*[cards.section(f"item {i}", discord.ui.Button(label="x", url="https://e.com"))
                          for i in range(60)])
    assert_fits(many, "component overflow")


EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿]️?|\\d️⃣")
ALLOWED = {"🟢", "🟡", "🔴", "⚪"}
EXCEPTIONS = {("cogs/automations/templates.py", "👍"),
              ("cogs/backup/restore.py", "⭐"),
              ("__main__.py", "✓"), ("__main__.py", "✗"), ("core/bot.py", "✗")}


def test_no_decorative_emoji_in_source():
    found = []
    for path in sorted((ROOT / "zdbf").rglob("*.py")):
        rel = path.relative_to(ROOT / "zdbf").as_posix()
        if rel == "ui/theme.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in EMOJI.findall(line):
                if m.rstrip("️") not in ALLOWED and (rel, m.rstrip("️")) not in EXCEPTIONS:
                    found.append(f"{rel}:{n}: {m}")
    assert not found, "decorative emoji found:\n" + "\n".join(found)


@pytest.mark.parametrize("builder", ["success", "info", "warning", "error"])
def test_level_cards_have_no_emoji(builder):
    view = getattr(cards, builder)("Title", "Body text")
    text = "".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert not [m for m in EMOJI.findall(text) if m.rstrip("️") not in ALLOWED]
