# SPDX-License-Identifier: Apache-2.0
import re
import zipfile

from zdbf.cogs.dashboard import export
from zdbf.cogs.dashboard.link import Link, LinkStore


def test_archive_holds_the_site_and_a_fresh_setup_key(tmp_path):
    key = export.new_setup_key()
    assert re.fullmatch(r"[A-Z2-7]{4}(-[A-Z2-7]{4}){3}", key) and key != export.new_setup_key()
    target = tmp_path / "out" / "site.zip"
    count, size = export.build_archive(target, key)
    assert size == target.stat().st_size and count > 40
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert all(n.startswith("zdbf-dashboard/") for n in names) and len(names) == count
        for needed in ("index.php", "setup.php", ".htaccess", "app/.htaccess", "data/.htaccess", "app/Auth.php",
                       "api/bot/pull.php", "assets/js/app.js", "assets/css/tokens.css", "assets/fonts/zdbf-grotesk-latin.woff2",
                       "assets/LICENSES.txt", "nginx.example.conf", "data/setup-key.php"):
            assert f"zdbf-dashboard/{needed}" in names, needed
        data = {n for n in names if n.startswith("zdbf-dashboard/data/")}
        assert data == {"zdbf-dashboard/data/.htaccess", "zdbf-dashboard/data/setup-key.php"}
        key_file = archive.read("zdbf-dashboard/data/setup-key.php").decode()
        assert f"return '{key}';" in key_file and "defined('ZDBF_DASHBOARD')" in key_file
        assert not any("__pycache__" in n or n.endswith((".sqlite", ".log", ".tmp")) for n in names)


def test_link_store_round_trip_and_private_file(tmp_path):
    store = LinkStore(tmp_path / "dashboard" / "link.json")
    assert store.load() is None and not store.delete()
    link = Link(url="https://example.com/dash", install_id="abc", secret="f" * 64, bot_id="1")
    store.save(link)
    loaded = store.load()
    assert loaded == link and loaded.endpoint("api/bot/pull.php") == "https://example.com/dash/api/bot/pull.php"
    if hasattr(store.path, "stat") and store.path.stat().st_mode & 0o777 != 0o666:
        assert store.path.stat().st_mode & 0o077 == 0
    store.path.write_text("not json")
    assert store.load() is None
    assert store.delete() and store.load() is None


async def test_export_command_sends_the_archive_privately_and_visibly(tmp_cwd):
    from types import SimpleNamespace

    import discord

    from zdbf.cogs.dashboard.cog import Dashboard
    from zdbf.core.config import Settings

    bot = SimpleNamespace(db=None, config=SimpleNamespace(settings=Settings()), repo_url="https://example.invalid")
    cog = Dashboard(bot)
    sent: dict[str, list] = {"dm": [], "channel": []}

    async def dm(*, view, files=(), **_):
        sent["dm"].append((view, list(files)))

    async def channel(*, view, **_):
        sent["channel"].append(view)

    async def defer(**_):
        return None

    ctx = SimpleNamespace(interaction=None, guild=object(), author=SimpleNamespace(send=dm), send=channel, defer=defer)
    await Dashboard.dashboard_export.callback(cog, ctx)

    (view, files), = sent["dm"]
    archive = tmp_cwd / "data" / "dashboard" / "zdbf-dashboard.zip"
    assert archive.is_file() and [f.filename for f in files] == ["zdbf-dashboard.zip"]
    items = list(view.walk_children())
    shown = [i for i in items if isinstance(i, discord.ui.File)]
    assert len(shown) == 1 and shown[0].url == "attachment://zdbf-dashboard.zip"
    text = "\n".join(i.content for i in items if isinstance(i, discord.ui.TextDisplay))
    assert str(archive.resolve().as_posix()) in text, "the card must show the full path, not a relative one"
    key = re.search(r"[A-Z2-7]{4}(?:-[A-Z2-7]{4}){3}", text).group(0)
    with zipfile.ZipFile(archive) as packed:
        assert f"return '{key}';" in packed.read("zdbf-dashboard/data/setup-key.php").decode()
    public = "\n".join(i.content for v in sent["channel"] for i in v.walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert sent["channel"] and key not in public and "DM" in public
    for f in files:
        f.close()
