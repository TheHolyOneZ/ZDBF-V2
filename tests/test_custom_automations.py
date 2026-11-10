# SPDX-License-Identifier: Apache-2.0
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from zdbf.cogs.automations import actions as A
from zdbf.cogs.automations.engine import (
    Automation,
    check_conditions,
    check_url,
    render,
    safe_math,
    validate_conditions,
)


def test_render_functions_and_builtins():
    out = render("{user} {math:2*(3+4)} {math:10/4} {random:7-7} {date} {nope}", user="Ann")
    parts = out.split()
    assert parts[:4] == ["Ann", "14", "2.5", "7"]
    assert len(parts[4]) == 10 and parts[5] == "{nope}"
    assert render("{math:1/0} {random:x-y}") == "{math:1/0} {random:x-y}"
    assert render("{timestamp}", timestamp="custom") == "custom"


@pytest.mark.parametrize("expr", ["__import__('os')", "2**999", "a+1", "(1).real", "[1]", "9e15*9e15"])
def test_safe_math_rejects(expr):
    with pytest.raises(ValueError):
        safe_math(expr)


def test_check_url():
    assert check_url("https://discord.com/api/webhooks/1/x") is None
    assert check_url("http://example.com")
    assert check_url("https://localhost/x")
    assert check_url("https://127.0.0.1/x")
    assert check_url("https://10.0.0.5/x")
    assert check_url("https://[::1]/x")


def _member(top: int, role_pos: int) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.roles = []
    member.top_role.position = top
    member.guild.get_role.return_value = SimpleNamespace(position=role_pos)
    return member


def test_new_conditions():
    above = {"rules": [{"type": "role_above", "role_id": 1}]}
    below = {"rules": [{"type": "role_below", "role_id": 1}]}
    assert check_conditions(above, member=_member(5, 3))
    assert not check_conditions(above, member=_member(2, 3))
    assert check_conditions(below, member=_member(2, 3))
    count = {"rules": [{"type": "message_count", "operator": ">=", "value": 10}]}
    assert check_conditions(count, context={"message_count": 10})
    assert not check_conditions(count, context={"message_count": 9})
    var = {"rules": [{"type": "variable", "name": "content", "operator": "contains", "value": "HELP"}]}
    assert check_conditions(var, content="i need help")
    assert not check_conditions(var, content="nothing")
    _, err = validate_conditions([{"type": "message_count", "operator": "~", "value": 1}])
    assert err and "operator" in err


def test_validate_actions():
    good = {"trigger": "message", "match": "contains", "keyword": "hi",
            "actions": [{"type": "send_message", "message": "hello"}, {"type": "delay", "seconds": 5}]}
    assert A.validate_actions(good) == []
    bad = {"trigger": "schedule", "interval_minutes": 0, "actions": [
        {"type": "add_role"}, {"type": "webhook", "url": "http://x"}, {"type": "delay", "seconds": 900}]}
    errors = " | ".join(A.validate_actions(bad))
    for needle in ("Role is required", "https://", "between 1 and 300", "at least 1 minute", "no member"):
        assert needle in errors
    too_many = {"trigger": "message", "actions": [{"type": "delay", "seconds": 1}] * 16}
    assert any("at most" in e for e in A.validate_actions(too_many))
    regex = {"trigger": "message", "match": "regex", "keyword": "([", "actions": []}
    assert any("regular expression" in e for e in A.validate_actions(regex))


def _auto(hook_id: str, **config) -> Automation:
    return Automation(hook_id=hook_id, guild_id=1, name=hook_id, template="custom", config=config)


def test_accepts_filters():
    msg = {"message": SimpleNamespace(content="Please HELP me")}
    assert A.accepts(_auto("a", trigger="message", match="contains", keyword="help"), "message", msg)
    assert not A.accepts(_auto("a", trigger="message", match="exact", keyword="help"), "message", msg)
    assert A.accepts(_auto("a", trigger="message", match="regex", keyword=r"^please"), "message", msg)
    assert not A.accepts(_auto("a", trigger="member_join"), "message", msg)
    sched = _auto("sched-test", trigger="schedule", interval_minutes=60)
    A._last_tick.pop("sched-test", None)
    assert A.accepts(sched, "tick", {})
    assert not A.accepts(sched, "tick", {})


class FakeRuntime:
    def __init__(self, autos):
        self.sent = []
        self.cog = SimpleNamespace(find=lambda hid: autos.get(hid))
        self.bot = None

    def channel(self, value):
        return f"channel-{value}"

    def throttle(self, key, seconds):
        return True

    async def send(self, channel, text, **kwargs):
        self.sent.append((channel, text))


def _ctx():
    return {"guild": object(), "member": None, "channel": "event-channel",
            "values": {"user": "Ann", "server": "Test"}, "delay_total": 0.0}


async def test_actions_run_in_order_and_chain():
    second = _auto("b", trigger="message", actions=[{"type": "send_message", "message": "second {math:1+1}"}])
    first = _auto("a", trigger="message", actions=[
        {"type": "send_message", "message": "hi {user}"},
        {"type": "delay", "seconds": 0.01},
        {"type": "send_message", "channel_id": 42, "message": "in {server}"},
        {"type": "trigger_automation", "hook_id": "b"},
    ])
    rt = FakeRuntime({"a": first, "b": second})
    await A.run_actions(rt, first, first.config["actions"], _ctx())
    assert rt.sent == [("event-channel", "hi Ann"), ("channel-42", "in Test"), ("event-channel", "second 2")]


async def test_loops_and_depth_are_stopped():
    a = _auto("a", actions=[{"type": "trigger_automation", "hook_id": "b"}])
    b = _auto("b", actions=[{"type": "trigger_automation", "hook_id": "a"}])
    with pytest.raises(A.ActionError, match="loop"):
        await A.run_actions(FakeRuntime({"a": a, "b": b}), a, a.config["actions"], _ctx())
    chain = {f"h{i}": _auto(f"h{i}", actions=[{"type": "trigger_automation", "hook_id": f"h{i + 1}"}])
             for i in range(10)}
    with pytest.raises(A.ActionError, match="levels deep"):
        await A.run_actions(FakeRuntime(chain), chain["h0"], chain["h0"].config["actions"], _ctx())


async def test_member_actions_without_member_fail_but_others_run():
    auto = _auto("a", actions=[{"type": "add_role", "role_id": 1}, {"type": "send_message", "message": "still"}])
    rt = FakeRuntime({})
    with pytest.raises(A.ActionError, match="no member"):
        await A.run_actions(rt, auto, auto.config["actions"], _ctx())
    assert rt.sent == [("event-channel", "still")]
    auto.config["stop_on_error"] = True
    rt = FakeRuntime({})
    with pytest.raises(A.ActionError):
        await A.run_actions(rt, auto, auto.config["actions"], _ctx())
    assert rt.sent == []


async def test_dispatch_cooldown_and_history(tmp_cwd):
    from zdbf.cogs.automations.cog import Automations
    from zdbf.core.database import Database

    db = Database("data/zdbf.db")
    await db.connect()
    try:
        bot = SimpleNamespace(db=db, alerts=SimpleNamespace(send=AsyncMock()), get_guild=lambda _id: SimpleNamespace(name="Test", member_count=2),
                              get_channel=lambda _id: None)
        cog = Automations(bot)  # type: ignore[arg-type]
        sent = []

        async def fake_send(channel, text, **kwargs):
            sent.append(text)

        cog.runtime.send = fake_send  # type: ignore[method-assign]
        auto = _auto("c1", trigger="message", match="contains", keyword="ping",
                     actions=[{"type": "send_message", "message": "pong"}], __cooldown={"seconds": 60, "per": "server"})
        auto.created_by = 1
        cog._add(auto)
        message = SimpleNamespace(author=object(), channel="chan", content="ping", jump_url="x")
        for _ in range(3):
            await cog.dispatch(1, "message", {"message": message}, channel_id=5, content="ping")
            await asyncio.gather(*cog._tasks)
        assert sent == ["pong"]
        await cog._flush()
        rows = await db.fetchall("SELECT * FROM automation_runs WHERE hook_id = 'c1'")
        assert len(rows) == 1 and rows[0]["ok"] == 1 and rows[0]["event"] == "message"
        view = await cog.history_view(auto, 1)
        view.build()
        assert view.page_count == 1
        await cog.delete_automation(auto)
        assert await db.fetchval("SELECT COUNT(*) FROM automation_runs WHERE hook_id = 'c1'") == 0
    finally:
        await db.close()


def test_v1_conditions_and_actions_convert():
    import tools.migrate_v1 as m

    cond = m.convert_conditions({"logic": "OR", "rules": [
        {"type": "role_hierarchy", "role_id": "5", "comparison": "above"},
        {"type": "custom_variable", "variable": "content", "operator": "contains", "value": "x"},
        {"type": "user_age", "min_days": 3}, {"type": "mystery"}]})
    assert cond["logic"] == "or"
    assert [r["type"] for r in cond["rules"]] == ["role_above", "variable", "account_age"]
    assert validate_conditions(cond)[1] is None
    assert m.convert_action({"type": "timeout", "duration": 30}) == {"type": "timeout", "seconds": 30}
    assert m.convert_action({"type": "trigger_hook", "hook_id": "x"})["type"] == "trigger_automation"
    assert m.convert_action({"type": "nope"}) is None
