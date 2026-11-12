# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import asdict
from typing import Any

import discord

from ....core.config import ConfigError
from . import ActionContext, ActionError, action

_background: set[asyncio.Task[None]] = set()
PRESENCES = ("online", "idle", "dnd", "invisible")
ACTIVITIES = ("playing", "watching", "listening", "competing", "custom")


@action("system.diagnostics", "view", timeout=30)
async def diagnostics(ctx: ActionContext) -> dict[str, Any]:
    cog = ctx.bot.get_cog("Diagnostics")
    if cog is None:
        return {"enabled": False}
    report = cog.report()
    return {"enabled": True, "status": cog.status, "report": report,
            "history": [asdict(h) for h in list(cog.history)[-96:]],
            "thresholds": {"error_rate": cog.settings.error_rate_warn_percent,
                           "loop_lag_ms": cog.settings.loop_lag_threshold_ms}}


@action("system.health_check", "view", timeout=30)
async def health_check(ctx: ActionContext) -> dict[str, Any]:
    cog = ctx.bot.get_cog("Diagnostics")
    if cog is None:
        raise ActionError("The diagnostics module is switched off on the bot.")
    return {"snapshot": asdict(await cog.health_check())}


@action("system.shards", "view", timeout=20)
async def shards(ctx: ActionContext) -> dict[str, Any]:
    bot = ctx.bot
    monitor = bot.get_cog("Shard Monitor")
    guilds: dict[int, int] = {}
    for guild in bot.guilds:
        guilds[guild.shard_id] = guilds.get(guild.shard_id, 0) + 1
    out = []
    for sid, shard in sorted(bot.shards.items()):
        item: dict[str, Any] = {"id": sid, "latency_ms": round(shard.latency * 1000, 1) if shard.latency == shard.latency
                                else None, "closed": shard.is_closed(), "guilds": guilds.get(sid, 0)}
        if monitor is not None:
            m = monitor.m(sid)
            healthy, note = m.health()
            item.update(avg_ms=round(m.avg_ms, 1), uptime_pct=round(m.uptime_pct, 2), connects=m.connects,
                        disconnects=m.disconnects, resumes=m.resumes, messages=m.messages, commands=m.commands,
                        healthy=healthy, note=note, last_event=m.last_event,
                        history=[round(x, 1) for x in list(m.latencies)[-60:]])
        out.append(item)
    cluster = bot.get_cog("Cluster")
    cluster_info = None
    if cluster is not None:
        peer = getattr(cluster, "peer", None)
        cluster_info = {"mode": cluster.mode, "name": cluster.name, "address": f"{cluster.host}:{cluster.port}",
                        "running": bool(getattr(peer, "running", False)), **cluster.info()}
    return {"shards": out, "count": bot.shard_count or 1, "monitor": monitor is not None, "cluster": cluster_info}


def _hook(bot: Any, info: Any) -> dict[str, Any]:
    hid = info.hook_id
    return {"id": hid, "event": info.event, "module": getattr(info.callback, "__module__", "?"),
            "name": getattr(info.callback, "__qualname__", "?"), "priority": info.priority,
            "executions": info.executions, "failures": info.failures, "avg_ms": info.avg_ms,
            "disabled": hid in bot.hooks.disabled, "tripped": bot.hooks.breaker.is_open(hid)}


@action("system.hooks", "view", timeout=20)
async def hooks(ctx: ActionContext) -> dict[str, Any]:
    registry = ctx.bot.hooks
    history = [{"event": h.event, "at": h.timestamp, "ok": h.succeeded, "failed": h.failed, "errors": h.errors[:5],
                "delay_ms": round(h.queue_delay_ms, 1), "avg_ms": h.avg_ms} for h in list(registry.history)[-100:]]
    return {"hooks": [_hook(ctx.bot, h) for h in sorted(registry.all_hooks(), key=lambda h: (h.event, h.hook_id))],
            "history": list(reversed(history)), "running": registry.running, "queue": registry.queue_size,
            "metrics": registry.metrics}


@action("system.hook_toggle", "extensions", timeout=15,
        summary=lambda a: f"{'enable' if a.get('enabled') else 'disable'} event hook {a.get('id')}")
async def hook_toggle(ctx: ActionContext) -> dict[str, Any]:
    registry = ctx.bot.hooks
    hid = ctx.text("id", max_length=400)
    if registry.find(hid) is None:
        raise ActionError("That hook is not registered any more.")
    changed = registry.enable(hid) if ctx.flag("enabled") else registry.disable(hid)
    info = registry.find(hid)
    return {"changed": changed, "hook": _hook(ctx.bot, info) if info else None}


@action("system.plugins", "view", timeout=20)
async def plugins(ctx: ActionContext) -> dict[str, Any]:
    registry = ctx.bot.plugins
    out = []
    for name, meta in sorted(registry.all().items()):
        data = meta.to_dict()
        out.append({"name": name, "version": data["version"], "author": data["author"],
                    "description": data["description"], "dependencies": data["dependencies"],
                    "conflicts": data["conflicts_with"], "provides_hooks": data["provides_hooks"],
                    "listens_to_hooks": data["listens_to_hooks"], "commands": data["commands"],
                    "load_ms": round(data["load_time_ms"], 1), "problems": registry.check_dependencies(meta)
                    + registry.detect_conflicts(meta) + data["scan_errors"]})
    return {"plugins": out}


@action("system.alerts", "view", timeout=15)
async def alerts(ctx: ActionContext) -> dict[str, Any]:
    manager = ctx.bot.alerts
    channels = {}
    for system in ("default", "errors", "diagnostics", "eventhooks", "plugins", "extensions", "scheduler",
                   "backup", "marketplace", "dashboard"):
        channel_id = manager.channel_for(system)
        if channel_id:
            channel = ctx.bot.get_channel(channel_id)
            channels[system] = {"id": str(channel_id), "name": getattr(channel, "name", None)}
    return {"alerts": list(reversed(list(manager.recent))), "channels": channels}


@action("presence.get", "view", timeout=10)
async def presence_get(ctx: ActionContext) -> dict[str, Any]:
    settings = ctx.bot.config.settings.status
    overrides = ctx.bot.config.overrides.get("status", {})
    return {"interval": settings.interval, "rotation": [r.model_dump() for r in settings.rotation],
            "override": bool(overrides), "presences": list(PRESENCES), "activities": list(ACTIVITIES),
            "placeholders": ["guilds", "users", "shards", "commands", "prefix", "version"],
            "preview": [ctx.bot.format_status(r.text) for r in settings.rotation]}


@action("presence.set", "presence", timeout=20, summary=lambda a: "change the bot's status rotation")
async def presence_set(ctx: ActionContext) -> dict[str, Any]:
    config = ctx.bot.config
    try:
        if ctx.flag("reset"):
            await config.unset("status.rotation")
            await config.unset("status.interval")
        else:
            raw = ctx.args.get("rotation")
            if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
                raise ActionError("Add between 1 and 20 entries.")
            rotation = []
            for entry in raw:
                if not isinstance(entry, dict):
                    raise ActionError("An entry could not be read.")
                presence, kind = str(entry.get("presence", "online")), str(entry.get("type", "playing"))
                text = str(entry.get("text", "")).strip()[:128]
                if presence not in PRESENCES or kind not in ACTIVITIES or not text:
                    raise ActionError("Every entry needs a status, a type and a text.")
                rotation.append({"presence": presence, "type": kind, "text": text})
            await config.set("status.rotation", rotation)
            await config.set("status.interval", ctx.integer("interval", default=config.settings.status.interval,
                                                            minimum=10, maximum=3600))
    except ConfigError as exc:
        raise ActionError(str(exc)) from exc
    first = config.settings.status.rotation[0] if config.settings.status.rotation else None
    if first is not None:
        text = ctx.bot.format_status(first.text)
        activity: discord.BaseActivity = (discord.CustomActivity(name=text) if first.type == "custom"
                                          else discord.Activity(type=getattr(discord.ActivityType, first.type), name=text))
        with contextlib.suppress(Exception):
            await ctx.bot.change_presence(status=discord.Status(first.presence), activity=activity)
    return await presence_get(ctx)


@action("system.shutdown", "system", timeout=15, summary=lambda a: "shut the bot down")
async def shutdown(ctx: ActionContext) -> dict[str, Any]:
    bot = ctx.bot

    async def later() -> None:
        await asyncio.sleep(3)
        await bot.close()

    task = asyncio.get_running_loop().create_task(later())
    _background.add(task)
    task.add_done_callback(_background.discard)
    return {"at": time.time() + 3}


@action("system.caches", "view", timeout=10)
async def caches(ctx: ActionContext) -> dict[str, Any]:
    from ....core.storage import global_file_handler

    bot = ctx.bot
    return {"files": global_file_handler.get_cache_stats(), "prefixes": len(bot.prefix_cache),
            "prefix_hits": bot.prefix_cache.hits, "permissions": len(bot._perm_cache)}


@action("system.clear_caches", "settings", timeout=10, summary=lambda a: "clear the bot's caches")
async def clear_caches(ctx: ActionContext) -> dict[str, Any]:
    from ....core.storage import global_file_handler

    dropped = global_file_handler.clear_all_cache()
    ctx.bot.prefix_cache.clear()
    ctx.bot._perm_cache.clear()
    return {"dropped": dropped}
