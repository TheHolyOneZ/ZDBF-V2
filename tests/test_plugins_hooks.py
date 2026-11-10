# SPDX-License-Identifier: Apache-2.0
import types

from zdbf.core.hooks import CircuitBreaker, HookBus
from zdbf.core.plugins import PluginMetadata, PluginRegistry, compare_versions, read_static_metadata


def test_compare_versions():
    assert compare_versions("1.4.2", ">=1.2")
    assert not compare_versions("1.1", ">=1.2")
    assert compare_versions("2.0", "")
    assert compare_versions("1.0", "1.0.0")
    assert compare_versions("1.5", "~=1.2")
    assert not compare_versions("2.0", "~=1.2")
    assert compare_versions("1.0.0 (BETA)", "==1.0")


def test_static_metadata(tmp_path):
    f = tmp_path / "ext.py"
    f.write_text('__version__ = "1.2"\n__dependencies__ = ["eco"]\n__conflicts__ = ["old"]\nimport os\n')
    meta = read_static_metadata(f)
    assert meta == {"__version__": "1.2", "__dependencies__": ["eco"], "__conflicts__": ["old"]}


def _registry():
    return PluginRegistry(types.SimpleNamespace(extensions={}, cogs={}))


def test_dependencies_conflicts_cycles():
    reg = _registry()
    reg.plugins["eco"] = PluginMetadata("eco", version="1.0", dependencies={"shop": ""})
    shop = PluginMetadata("shop", dependencies={"eco": ">=2.0"}, conflicts_with={"legacy"})
    assert reg.check_dependencies(shop) == ["eco (requires >=2.0, found 1.0)"]
    assert reg.find_cycle("shop", shop) == ["shop", "eco", "shop"]
    reg.plugins["legacy"] = PluginMetadata("legacy")
    assert reg.detect_conflicts(shop) == ["legacy"]
    problems = reg.validate(shop)
    assert len(problems) == 3
    reg.enforce_dependencies = reg.enforce_conflicts = False
    assert len(reg.validate(shop)) == 1


def test_circuit_breaker():
    cb = CircuitBreaker(threshold=3, window=60, cooldown=60)
    assert not cb.record_failure("h")
    assert not cb.record_failure("h")
    assert cb.record_failure("h")
    assert cb.is_open("h")
    cb.reset("h")
    assert not cb.is_open("h")


async def test_hook_bus_dispatch_and_failures():
    async def send(*a, **k):
        return False

    bot = types.SimpleNamespace(alerts=types.SimpleNamespace(send=send))
    bus = HookBus(bot, timeout=1)
    seen = []

    async def ok(bot, value):
        seen.append(value)

    async def bad(bot, value):
        raise RuntimeError("boom")

    def not_async(bot, value):
        pass

    assert bus.register("evt", ok, priority=1)
    assert bus.register("evt", bad)
    assert not bus.register("evt", not_async)
    entry = await bus.emit_now("evt", value=42)
    assert seen == [42] and entry.succeeded == 1 and entry.failed == 1
    hook_id = bus.hooks["evt"][1].hook_id
    assert bus.disable(hook_id)
    entry = await bus.emit_now("evt", value=1)
    assert entry.failed == 0
    assert bus.unregister("evt", ok)


async def test_disabled_hooks_survive_restart_and_registry_exports(tmp_cwd):
    import asyncio
    import json
    from types import SimpleNamespace

    from zdbf.core.database import Database
    from zdbf.core.hooks import HookBus
    from zdbf.core.plugins import PluginRegistry

    db = Database("data/zdbf.db")
    await db.connect()
    try:
        bot = SimpleNamespace(db=db, extensions={}, cogs={})
        bus = HookBus(bot)  # type: ignore[arg-type]

        async def handler(**_):
            return None

        bus.register("on_test", handler)
        hook_id = bus.all_hooks()[0].hook_id
        assert bus.disable(hook_id)
        await asyncio.gather(*bus._pending_saves)
        fresh = HookBus(bot)  # type: ignore[arg-type]
        await fresh.load_disabled()
        assert hook_id in fresh.disabled

        registry = PluginRegistry(bot)  # type: ignore[arg-type]
        await registry.register_plugin("demo", version="1.2.0", author="me")
        assert await registry.export()
        data = json.loads((tmp_cwd / "data" / "plugin_registry.json").read_text())
        assert data["total_plugins"] == 1 and data["plugins"]["demo"]["version"] == "1.2.0"
    finally:
        await db.close()
