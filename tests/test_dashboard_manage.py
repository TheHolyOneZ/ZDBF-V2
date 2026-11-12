# SPDX-License-Identifier: Apache-2.0
import sqlite3
from types import SimpleNamespace

import pytest
from _dashboard import FakeCog, command

from zdbf.cogs.dashboard import actions
from zdbf.cogs.dashboard.actions import REGISTRY, ActionError, catalogue
from zdbf.cogs.dashboard.actions.automations import _clean_config
from zdbf.cogs.dashboard.panels import Panel, PanelError, clean_blocks, panels


@pytest.fixture(autouse=True)
def loaded():
    actions.load_all()
    yield
    for panel_id in list(panels.panels):
        panels.unregister(panel_id)


def test_panel_blocks_are_reduced_to_plain_data():
    blocks = clean_blocks([
        {"type": "stats", "title": "T" * 500, "items": [{"label": "Users", "value": 5}, "junk"]},
        {"type": "html", "html": "<script>alert(1)</script>"},
        {"type": "table", "columns": ["a", "b"], "rows": [[1, "x" * 1000, "extra"], "bad"]},
        {"type": "form", "action": "save", "fields": [{"key": "k", "label": "K", "kind": "text"},
                                                       {"key": "x", "kind": "script"}]},
        {"type": "buttons", "buttons": [{"action": "go", "label": "Go", "style": "evil"}]},
        "nonsense",
    ])
    assert [b["type"] for b in blocks] == ["stats", "table", "form", "buttons"]
    assert len(blocks[0]["title"]) == 120 and blocks[0]["items"] == [{"label": "Users", "value": 5, "hint": None}]
    assert blocks[1]["rows"] == [[1, "x" * 300]]
    assert [f["key"] for f in blocks[2]["fields"]] == ["k"]
    assert blocks[3]["buttons"][0]["style"] == "secondary"
    with pytest.raises(ActionError):
        clean_blocks({"type": "text"})


async def test_panels_become_actions_with_their_capabilities():
    seen = []

    async def render(ctx):
        return [{"type": "text", "text": f"count {len(seen)}"}]

    async def bump(ctx):
        seen.append(ctx.args.get("n"))
        return "Bumped."

    panels.register(Panel("demo", "Demo", render, actions={"bump": bump}, action_capability="settings",
                          module="extensions.demo"))
    assert catalogue()["panel.demo"] == "view" and catalogue()["panel.demo.bump"] == "settings"
    cog = FakeCog(capabilities=["view", "settings"], approval=["settings"])
    shown = await cog.dispatcher.handle(command("panel.demo"))
    assert shown["data"]["blocks"] == [{"type": "text", "title": None, "text": "count 0"}]
    done = await cog.dispatcher.handle(command("panel.demo.bump", args={"n": 3}))
    assert done["data"]["message"] == "Bumped." and done["data"]["blocks"][0]["text"] == "count 1"
    assert cog.approvals.calls and seen == [3]
    off = FakeCog(capabilities=["view"])
    refused = await off.dispatcher.handle(command("panel.demo.bump"))
    assert refused["status"] == "denied" and seen == [3]
    assert panels.unregister_module("extensions.demo") == 1
    assert "panel.demo" not in REGISTRY and "panel.demo.bump" not in REGISTRY


def test_panel_registration_is_validated():
    async def render(ctx):
        return []

    for bad in (Panel("Bad Id", "x", render), Panel("ok", "x", render, capability="root"),
                Panel("ok", "x", render, actions={"Not ok": render})):
        with pytest.raises(PanelError):
            panels.register(bad)


async def test_database_browser_is_read_only_and_hides_secrets(tmp_path):
    path = tmp_path / "zdbf.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE things (id INTEGER PRIMARY KEY, name TEXT, api_token TEXT)")
        conn.executemany("INSERT INTO things (name, api_token) VALUES (?, ?)",
                         [(f"item {i}", f"secret-{i}") for i in range(60)])
    cog = FakeCog(capabilities=["database"])
    cog.bot.db = SimpleNamespace(path=path)
    tables = await cog.dispatcher.handle(command("database.tables"))
    assert tables["data"]["tables"][0]["name"] == "things" and tables["data"]["tables"][0]["rows"] == 60
    rows = await cog.dispatcher.handle(command("database.rows", args={"table": "things", "limit": 10}))
    data = rows["data"]
    assert data["total"] == 60 and len(data["rows"]) == 10 and data["rows"][0][0] == 60
    assert {r[2] for r in data["rows"]} == {"[hidden]"}
    found = await cog.dispatcher.handle(command("database.rows", args={"table": "things", "search": "item 7"}))
    assert found["data"]["total"] == 1
    hidden = await cog.dispatcher.handle(command("database.rows", args={"table": "things", "search": "secret-3"}))
    assert hidden["data"]["total"] == 0
    bad = await cog.dispatcher.handle(command("database.rows", args={"table": "things; DROP TABLE things"}))
    assert bad["status"] == "error"
    bad = await cog.dispatcher.handle(command("database.rows", args={"table": "things", "order": "id; --"}))
    assert bad["status"] == "error"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM things").fetchone()[0] == 60


def test_automation_values_are_typed_from_the_form():
    param = SimpleNamespace
    template = SimpleNamespace(params=(
        param(key="channel_id", label="Channel", kind="channel", choices=()),
        param(key="roles", label="Roles", kind="roles", choices=()),
        param(key="xp", label="XP", kind="number", choices=()),
        param(key="card", label="Card", kind="bool", choices=()),
        param(key="mapping", label="Mapping", kind="json", choices=()),
        param(key="action", label="Action", kind="choice", choices=("delete", "warn")),
    ))
    out = _clean_config(template, {"channel_id": "123", "roles": ["1", "2"], "xp": "10", "card": 1,
                                   "mapping": '{"a": 1}', "action": "warn", "unknown": "x"})
    assert out == {"channel_id": 123, "roles": [1, 2], "xp": 10, "card": True, "mapping": {"a": 1}, "action": "warn"}
    for bad in ({"channel_id": "#general"}, {"xp": "ten"}, {"mapping": "{"}, {"action": "ban"}, {"roles": "1"}):
        with pytest.raises(ActionError):
            _clean_config(template, bad)


async def test_presence_rotation_is_validated():
    cog = FakeCog(capabilities=["view", "presence"])
    stored = {}

    async def set_value(key, value):
        stored[key] = value

    cog.bot.config = SimpleNamespace(set=set_value, settings=SimpleNamespace(status=SimpleNamespace(interval=20, rotation=[])),
                                     overrides={})
    bad = await cog.dispatcher.handle(command("presence.set", args={"rotation": [{"presence": "busy", "type": "x", "text": "hi"}]}))
    assert bad["status"] == "error" and not stored
    bad = await cog.dispatcher.handle(command("presence.set", args={"rotation": []}))
    assert bad["status"] == "error"
