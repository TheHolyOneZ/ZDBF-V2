# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ....core.config import ConfigError
from ....core.extensions import BUILTIN_MODULES, ExtensionResult
from ..sandbox import SandboxError
from . import ActionContext, ActionError, action


def _file_link(ctx: ActionContext, path: Path | None) -> str | None:
    if path is None:
        return None
    box = ctx.cog.sandbox
    try:
        rel = Path(os.path.relpath(os.path.realpath(path), box.base)).as_posix()
        box.resolve(rel)
    except (SandboxError, ValueError):
        return None
    return rel


def _result(result: ExtensionResult) -> dict[str, Any]:
    return {"name": result.name, "ok": result.ok, "action": result.action, "ms": round(result.elapsed_ms, 1),
            "error": result.error, "note": result.note}


def _user_module(ctx: ActionContext) -> str:
    name = ctx.text("name", max_length=200).strip()
    mgr = ctx.bot.ext
    module = mgr.module_for(name)
    if mgr.is_builtin(module) or name in BUILTIN_MODULES:
        raise ActionError("Built-in modules are switched on and off in config.toml under [modules].")
    return module


@action("extensions.list", "view", timeout=20)
async def listing(ctx: ActionContext) -> dict[str, Any]:
    bot = ctx.bot
    mgr = bot.ext
    loaded = set(bot.extensions)
    builtin = []
    for key, module in BUILTIN_MODULES.items():
        builtin.append({
            "name": key, "module": module, "loaded": module in loaded, "enabled": bot.config.module_enabled(key),
            "ms": round(mgr.load_times.get(key, 0.0), 1), "error": mgr.failed.get(module),
            "traceback": mgr.tracebacks.get(module),
        })
    modules = mgr.discover()
    modules += sorted(m for m in loaded if not mgr.is_builtin(m) and m not in modules)
    blacklist = {b.removesuffix(".py") for b in bot.config.settings.extensions.blacklist}
    marketplace = bot.get_cog("Marketplace")
    installed = getattr(marketplace, "installed", {}) or {}
    user = []
    for module in modules:
        name = mgr.short_name(module)
        meta = bot.plugins.get(name)
        path = mgr.path_for(module)
        record = installed.get(f"{name}.py")
        user.append({
            "name": name, "module": module, "loaded": module in loaded, "blacklisted": name in blacklist,
            "ms": round(mgr.load_times.get(name, 0.0), 1), "error": mgr.failed.get(module),
            "traceback": mgr.tracebacks.get(module), "file": _file_link(ctx, path),
            "version": meta.version if meta and meta.version != "unknown" else (record or {}).get("version"),
            "author": meta.author if meta and meta.author != "unknown" else None,
            "description": meta.description if meta and meta.description != "No description" else None,
            "commands": sorted(meta.commands) if meta else [],
            "marketplace": {"id": record.get("id"), "version": record.get("version")} if record else None,
        })
    settings = bot.config.settings.extensions
    watcher = getattr(mgr, "_watcher", None)
    return {
        "builtin": builtin, "extensions": user, "directory": str(settings.directory),
        "hot_reload": settings.hot_reload, "watching": watcher is not None and not watcher.done(),
        "interval": settings.hot_reload_interval, "manage": ctx.cog.policy.allows("extensions"),
    }


@action("extensions.load", "extensions", timeout=120, summary=lambda a: f"load {a.get('name')}")
async def load(ctx: ActionContext) -> dict[str, Any]:
    module = _user_module(ctx)
    return _result(await ctx.bot.ext.load(module))


@action("extensions.unload", "extensions", timeout=60, summary=lambda a: f"unload {a.get('name')}")
async def unload(ctx: ActionContext) -> dict[str, Any]:
    module = _user_module(ctx)
    return _result(await ctx.bot.ext.unload(module))


@action("extensions.reload", "extensions", timeout=120, summary=lambda a: f"reload {a.get('name')}")
async def reload(ctx: ActionContext) -> dict[str, Any]:
    module = _user_module(ctx)
    return _result(await ctx.bot.ext.reload(module))


@action("extensions.hot_reload", "extensions", timeout=20,
        summary=lambda a: f"turn hot reload {'on' if a.get('enabled') else 'off'}")
async def hot_reload(ctx: ActionContext) -> dict[str, Any]:
    enabled = ctx.args.get("enabled")
    if not isinstance(enabled, bool):
        raise ActionError("missing value: enabled")
    try:
        await ctx.bot.config.set("extensions.hot_reload", enabled)
    except ConfigError as exc:
        raise ActionError(str(exc)) from exc
    if enabled:
        ctx.bot.ext.start_watcher()
    else:
        await ctx.bot.ext.stop_watcher()
    return {"hot_reload": enabled}
