# SPDX-License-Identifier: Apache-2.0
import asyncio

import pytest
from _dashboard import FakeCog, command

from zdbf.cogs.dashboard import actions
from zdbf.cogs.dashboard.actions import ActionError, action
from zdbf.cogs.dashboard.approvals import ApprovalManager
from zdbf.cogs.dashboard.sandbox import SandboxError


@pytest.fixture(autouse=True)
def registry():
    actions.load_all()
    saved = dict(actions.REGISTRY)
    ran: list[str] = []

    @action("test.echo", "view")
    async def echo(ctx):
        ran.append(ctx.command_id)
        return {"args": ctx.args, "user": ctx.user.get("name")}

    @action("test.write", "files.write", summary=lambda a: f"write {a.get('path')}")
    async def write(ctx):
        ran.append(ctx.command_id)
        return {"written": ctx.text("path")}

    @action("test.reload", "extensions")
    async def reload(ctx):
        ran.append(ctx.command_id)
        return None

    @action("test.boom", "view")
    async def boom(ctx):
        raise RuntimeError("secret detail that must not leak")

    @action("test.bad", "view")
    async def bad(ctx):
        raise ActionError("that name is taken")

    @action("test.escape", "files.read")
    async def escape(ctx):
        raise SandboxError("that path is outside the folders the dashboard may open")

    @action("test.slow", "view", timeout=0.05)
    async def slow(ctx):
        await asyncio.sleep(1)

    yield ran
    actions.REGISTRY.clear()
    actions.REGISTRY.update(saved)


async def test_allowed_action_runs_and_returns_data(registry):
    cog = FakeCog()
    result = await cog.dispatcher.handle(command("test.echo", args={"a": 1}))
    assert result["status"] == "done" and result["data"] == {"args": {"a": 1}, "user": "tester"}
    assert cog.audit.rows == []
    result = await cog.dispatcher.handle(command("test.reload"))
    assert result["status"] == "done" and result["data"] == {}
    assert cog.audit.outcomes() == ["ok"]


async def test_capability_that_is_off_is_refused_without_running(registry):
    cog = FakeCog()
    result = await cog.dispatcher.handle(command("test.write", args={"path": "extensions/x.py"}))
    assert result["status"] == "denied" and "files.write" in result["error"]
    assert registry == [] and cog.approvals.calls == []
    assert cog.audit.outcomes() == ["refused"]


async def test_dangerous_capability_waits_for_approval(registry):
    cog = FakeCog(capabilities=["view", "files.write"])
    cog.approvals.answer = (False, "Denied by owner.")
    denied = await cog.dispatcher.handle(command("test.write", args={"path": "extensions/x.py"}))
    assert denied["status"] == "denied" and denied["error"] == "Denied by owner."
    assert registry == []
    assert cog.results[-1]["status"] == "awaiting_approval"
    assert cog.approvals.calls[0]["summary"] == "write extensions/x.py"
    assert cog.approvals.calls[0]["capability"] == "files.write"
    cog.approvals.answer = (True, "Approved by owner.")
    ok = await cog.dispatcher.handle(command("test.write", args={"path": "extensions/x.py"}))
    assert ok["status"] == "done" and len(registry) == 1
    assert cog.audit.outcomes() == ["denied", "ok"]


async def test_an_action_can_report_progress(registry):
    @action("test.progress", "view")
    async def step(ctx):
        await ctx.progress("Channels (3)")
        return {}

    cog = FakeCog()
    result = await cog.dispatcher.handle(command("test.progress"))
    assert result["status"] == "done"
    assert {"id": result["id"], "status": "running", "note": "Channels (3)"} in cog.results


async def test_approval_can_be_switched_off_per_capability(registry):
    cog = FakeCog(capabilities=["view", "files.write"], approval=[])
    result = await cog.dispatcher.handle(command("test.write", args={"path": "extensions/x.py"}))
    assert result["status"] == "done" and cog.approvals.calls == []


async def test_capability_switched_off_while_waiting_is_not_run(registry):
    cog = FakeCog(capabilities=["view", "files.write"])

    async def revoke(**_):
        cog.settings.capabilities = ["view"]
        return True, "Approved."

    cog.approvals.request = revoke
    result = await cog.dispatcher.handle(command("test.write", args={"path": "extensions/x.py"}))
    assert result["status"] == "denied" and registry == []


async def test_lock_blocks_everything_but_reading(registry):
    cog = FakeCog(locked=True)
    assert (await cog.dispatcher.handle(command("test.echo")))["status"] == "done"
    result = await cog.dispatcher.handle(command("test.reload"))
    assert result["status"] == "denied" and "locked" in result["error"]
    assert len(registry) == 1


async def test_each_command_id_runs_once(registry):
    cog = FakeCog()
    cmd = command("test.echo", command_id="a" * 32)
    assert (await cog.dispatcher.handle(cmd))["status"] == "done"
    assert await cog.dispatcher.handle(dict(cmd)) is None
    assert registry == ["a" * 32]


async def test_old_and_future_commands_are_dropped(registry):
    cog = FakeCog()
    for age in (121, -121):
        result = await cog.dispatcher.handle(command("test.echo", age=age))
        assert result["status"] == "expired"
    missing = command("test.echo")
    del missing["issued_at"]
    assert (await cog.dispatcher.handle(missing))["status"] == "expired"
    assert registry == []


async def test_unknown_and_malformed_commands(registry):
    cog = FakeCog()
    assert (await cog.dispatcher.handle(command("nope.nothing")))["status"] == "error"
    for junk in (None, "x", [], {"id": 5, "type": "test.echo"}, {"id": "", "type": "test.echo"},
                 {"id": "x" * 65, "type": "test.echo"}, {"id": "ok", "type": None}):
        assert await cog.dispatcher.handle(junk) is None
    odd = command("test.echo")
    odd["args"], odd["user"] = "not a dict", ["not", "a", "dict"]
    result = await cog.dispatcher.handle(odd)
    assert result["status"] == "done" and result["data"] == {"args": {}, "user": None}


async def test_failures_report_safely(registry):
    cog = FakeCog()
    crash = await cog.dispatcher.handle(command("test.boom"))
    assert crash["status"] == "error" and "secret detail" not in crash["error"] and "RuntimeError" in crash["error"]
    assert (await cog.dispatcher.handle(command("test.bad")))["error"] == "that name is taken"
    assert "outside the folders" in (await cog.dispatcher.handle(command("test.escape")))["error"]
    assert "too long" in (await cog.dispatcher.handle(command("test.slow")))["error"]
    assert cog.audit.outcomes() == ["failed", "failed", "failed", "timeout"]
    assert cog.dispatcher.running == 0


async def test_argument_helpers(registry):
    ctx = actions.ActionContext(None, None, "id", "t", {"name": "abc", "n": "12", "flag": True, "big": "x" * 50})
    assert ctx.text("name") == "abc" and ctx.integer("n") == 12 and ctx.flag("flag") and not ctx.flag("other")
    assert ctx.text("missing", default="d") == "d" and ctx.integer("missing", default=3) == 3
    for call in (lambda: ctx.text("missing"), lambda: ctx.text("big", max_length=10), lambda: ctx.integer("name"),
                 lambda: ctx.integer("n", maximum=5), lambda: ctx.integer("flag")):
        with pytest.raises(ActionError):
            call()


def test_every_registered_action_names_a_real_capability():
    actions.load_all()
    from zdbf.cogs.dashboard.capabilities import NAMES

    assert actions.catalogue()["system.ping"] == "view"
    assert set(actions.catalogue().values()) <= NAMES
    with pytest.raises(ValueError):
        action("x.y", "made.up")


class _Owner:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.views = []
        self.sent = asyncio.Event()

    async def send(self, *, view, **_):
        self.views.append(view)
        self.sent.set()
        return None


async def _approvals(owners):
    from types import SimpleNamespace

    bot = SimpleNamespace(owner_id_set={o.id for o in owners})
    manager = ApprovalManager(bot)

    async def fake_owners():
        return owners

    manager._owners = fake_owners
    return manager


async def test_approval_grant_covers_same_user_and_capability_only():
    owner = _Owner(1)
    manager = await _approvals([owner])
    user = {"id": "7", "name": "mika", "role": "Admin"}

    async def press(approved: bool, grant: bool) -> None:
        await owner.sent.wait()
        owner.sent.clear()
        owner.views.pop().decision.settle(approved, grant, "owner#1")

    task = asyncio.create_task(manager.request(capability="files.write", action="files.write", summary="x",
                                               user=user, timeout=5))
    await press(True, True)
    assert await task == (True, "Approved by owner#1 for 15 minutes.")
    assert manager.has_grant("7", "files.write")
    assert not manager.has_grant("7", "config") and not manager.has_grant("8", "files.write")
    again = await manager.request(capability="files.write", action="files.write", summary="y", user=user, timeout=5)
    assert again[0] and not owner.views
    task = asyncio.create_task(manager.request(capability="config", action="config.set", summary="z", user=user, timeout=5))
    await press(False, False)
    assert await task == (False, "Denied by owner#1.")
    manager.clear_grants()
    assert not manager.has_grant("7", "files.write") and manager.pending == 0


async def test_approval_times_out_and_needs_a_reachable_owner():
    owner = _Owner(1)
    manager = await _approvals([owner])
    approved, note = await manager.request(capability="system", action="system.shutdown", summary="", user={"id": "7"}, timeout=0.05)
    assert not approved and "not answered" in note
    nobody = await _approvals([])
    approved, note = await nobody.request(capability="system", action="system.shutdown", summary="", user={"id": "7"}, timeout=1)
    assert not approved and "direct message" in note
