# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import datetime as dt
import json
from typing import Any

import discord

from ....cogs.automations.actions import ACTION_TYPES, MATCH_MODES, TRIGGERS
from ....cogs.automations.engine import validate_conditions
from ....cogs.automations.templates import TEMPLATES
from ....core.cron import CronExpression
from . import ActionContext, ActionError, action
from .servers import guild_of

CHANNEL_NAMES = {discord.ChannelType.text: "text", discord.ChannelType.news: "news",
                 discord.ChannelType.voice: "voice", discord.ChannelType.category: "category"}


def _cog(ctx: ActionContext) -> Any:
    cog = ctx.bot.get_cog("Automations")
    if cog is None:
        raise ActionError("The automations module is switched off on the bot ([modules] automations).")
    return cog


def _scheduler(ctx: ActionContext) -> Any:
    cog = ctx.bot.get_cog("Task Scheduler")
    if cog is None:
        raise ActionError("The scheduler module is switched off on the bot ([modules] scheduler).")
    return cog


def _param(p: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"key": p.key, "label": p.label, "kind": p.kind, "required": p.required,
                           "default": p.default, "description": p.description}
    if getattr(p, "choices", ()):
        out["choices"] = list(p.choices)
    if getattr(p, "channel_types", None):
        out["channel_types"] = [CHANNEL_NAMES.get(t, str(t)) for t in p.channel_types]
    if getattr(p, "show_if", None):
        out["show_if"] = {"key": p.show_if[0], "values": list(p.show_if[1])}
    return out


def _auto(auto: Any) -> dict[str, Any]:
    template = TEMPLATES.get(auto.template)
    return {"id": auto.hook_id, "guild_id": str(auto.guild_id), "name": auto.name, "template": auto.template,
            "template_name": template.name if template else auto.template, "config": auto.config,
            "conditions": auto.conditions, "enabled": auto.enabled, "runs": auto.run_count,
            "errors": auto.error_count, "last_run": auto.last_run, "last_error": auto.last_error,
            "created_at": auto.created_at, "updated_at": auto.updated_at}


def _find(ctx: ActionContext, cog: Any) -> Any:
    auto = cog.find(ctx.text("id", max_length=20))
    if auto is None:
        raise ActionError("That automation no longer exists.")
    return auto


def _clean_config(template: Any, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ActionError("The settings could not be read.")
    out: dict[str, Any] = {}
    for p in template.params:
        if p.key not in raw:
            continue
        value = raw[p.key]
        if value in (None, "", []):
            out[p.key] = None if p.kind != "roles" else []
            continue
        if p.kind in ("channel", "role"):
            if not str(value).isdigit():
                raise ActionError(f"{p.label} has to be picked from the list.")
            out[p.key] = int(value)
        elif p.kind == "roles":
            if not isinstance(value, list) or not all(str(v).isdigit() for v in value):
                raise ActionError(f"{p.label} has to be picked from the list.")
            out[p.key] = [int(v) for v in value][:20]
        elif p.kind == "bool":
            out[p.key] = bool(value)
        elif p.kind == "number":
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ActionError(f"{p.label} has to be a number.") from exc
            out[p.key] = int(number) if number.is_integer() else number
        elif p.kind == "json":
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ActionError(f"{p.label} is not valid JSON ({exc.msg}).") from exc
            out[p.key] = value
        elif p.kind == "actions":
            if not isinstance(value, list):
                raise ActionError(f"{p.label} has to be a list of actions.")
            out[p.key] = value[:25]
        elif p.kind == "choice":
            if p.choices and str(value) not in p.choices:
                raise ActionError(f"{p.label} has to be one of {', '.join(p.choices)}.")
            out[p.key] = str(value)
        else:
            out[p.key] = str(value)[:4000]
    return out


@action("automations.catalogue", "view", timeout=15)
async def catalogue(ctx: ActionContext) -> dict[str, Any]:
    _cog(ctx)
    return {
        "templates": [{"id": t.id, "name": t.name, "description": t.description,
                       "params": [_param(p) for p in t.params]} for t in TEMPLATES.values()],
        "actions": [{"id": a.id, "name": a.name, "description": a.description, "needs_member": a.needs_member,
                     "fields": [_param(f) for f in a.fields]} for a in ACTION_TYPES.values()],
        "triggers": {k: v[0] for k, v in TRIGGERS.items()}, "match_modes": list(MATCH_MODES),
    }


@action("automations.list", "view", timeout=20)
async def listing(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    return {"automations": [_auto(a) for a in sorted(cog.for_guild(guild.id), key=lambda a: a.name.lower())],
            "max": 25}


@action("automations.history", "view", timeout=20)
async def history(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    auto = _find(ctx, cog)
    await cog._flush()
    rows = await ctx.bot.db.fetchall(
        "SELECT * FROM automation_runs WHERE hook_id = ? ORDER BY id DESC LIMIT 200", (auto.hook_id,))
    return {"runs": [{"at": r["at"], "event": r["event"], "ok": bool(r["ok"]), "ms": r["duration_ms"],
                      "user_id": str(r["user_id"]) if r["user_id"] else None,
                      "channel_id": str(r["channel_id"]) if r["channel_id"] else None, "error": r["error"]}
                     for r in rows]}


@action("automations.save", "automations", timeout=60,
        summary=lambda a: f"{'change' if a.get('id') else 'create'} automation {a.get('name')}")
async def save(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    existing = None
    if ctx.args.get("id"):
        existing = _find(ctx, cog)
        if existing.guild_id != guild.id:
            raise ActionError("That automation belongs to another server.")
        template = TEMPLATES.get(existing.template)
    else:
        template = TEMPLATES.get(ctx.text("template", max_length=40))
    if template is None:
        raise ActionError("Unknown automation type.")
    name = ctx.text("name", max_length=100).strip()
    if not name:
        raise ActionError("Give the automation a name.")
    config = {**template.defaults(), **(existing.config if existing else {})}
    config.update(_clean_config(template, ctx.args.get("config", {})))
    conditions = None
    if "conditions" in ctx.args:
        conditions, error = validate_conditions(ctx.args["conditions"])
        if error:
            raise ActionError(f"Conditions: {error}")
    try:
        auto = await cog.save_automation(guild=guild, template=template, name=name, config=config,
                                         author_id=0, existing=existing)
    except ValueError as exc:
        raise ActionError(str(exc)) from exc
    if conditions is not None:
        auto.conditions = conditions
        await cog.persist(auto)
    return {"automation": _auto(auto)}


@action("automations.toggle", "automations", timeout=20)
async def toggle(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    auto = _find(ctx, cog)
    await cog.set_enabled(auto, ctx.flag("enabled"))
    return {"automation": _auto(auto)}


@action("automations.delete", "automations", timeout=30, summary=lambda a: f"delete automation {a.get('id')}")
async def delete(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    auto = _find(ctx, cog)
    await cog.delete_automation(auto)
    return {"deleted": auto.hook_id}


def _task(cog: Any, bot: Any, task: dict[str, Any]) -> dict[str, Any]:
    guild = bot.get_guild(int(task["guild_id"])) if task.get("guild_id") else None
    channel = bot.get_channel(int(task["channel_id"])) if task.get("channel_id") else None
    try:
        described = CronExpression.parse(task["cron_expression"]).describe()
    except ValueError:
        described = None
    return {"id": task["task_id"], "name": task["task_name"], "type": task["task_type"],
            "cron": task["cron_expression"], "cron_text": described, "payload": task.get("payload") or {},
            "enabled": task["enabled"], "next_run": task.get("next_run"), "last_run": task.get("last_run"),
            "runs": task.get("run_count", 0), "max_runs": task.get("max_runs"),
            "guild_id": str(task["guild_id"]) if task.get("guild_id") else None,
            "guild": guild.name if guild else None,
            "channel_id": str(task["channel_id"]) if task.get("channel_id") else None,
            "channel": getattr(channel, "name", None)}


def _find_task(ctx: ActionContext, cog: Any) -> dict[str, Any]:
    task = cog.tasks.get(ctx.text("id", max_length=20))
    if task is None:
        raise ActionError("That task no longer exists.")
    return task


@action("scheduler.list", "view", timeout=20)
async def tasks(ctx: ActionContext) -> dict[str, Any]:
    cog = _scheduler(ctx)
    return {"tasks": [_task(cog, ctx.bot, t) for t in cog.get_tasks()], "timezone": cog.tz.key,
            "max_per_guild": ctx.bot.config.settings.scheduler.max_tasks_per_guild}


@action("scheduler.preview", "view", timeout=10)
async def cron_preview(ctx: ActionContext) -> dict[str, Any]:
    cog = _scheduler(ctx)
    text = ctx.text("cron", max_length=120)
    try:
        expr = CronExpression.parse(text)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    runs = expr.upcoming(dt.datetime.now(cog.tz), 5)
    return {"ok": True, "text": expr.describe(), "runs": [r.isoformat() for r in runs], "timezone": cog.tz.key}


def _payload(ctx: ActionContext, kind: str, guild: discord.Guild) -> tuple[dict[str, Any], int | None]:
    message = ctx.text("message", default="", max_length=2000).strip()
    if kind == "message":
        channel = guild.get_channel(ctx.integer("channel_id", minimum=1))
        if not isinstance(channel, discord.TextChannel):
            raise ActionError("Pick a text channel.")
        if not channel.permissions_for(guild.me).send_messages:
            raise ActionError(f"The bot cannot send messages in #{channel.name}.")
        if not message:
            raise ActionError("Write the message.")
        title = ctx.text("title", default="", max_length=200).strip() or None
        return {"content": message, "title": title}, channel.id
    if kind == "hook":
        name = ctx.text("hook_name", default="scheduled_task", max_length=80).strip() or "scheduled_task"
        return {"hook_name": name, "data": {"guild_id": guild.id}}, None
    if kind == "log":
        return {"message": message or "scheduled task fired", "level": "INFO"}, None
    raise ActionError("Unknown task type.")


@action("scheduler.save", "scheduler", timeout=20,
        summary=lambda a: f"{'change' if a.get('id') else 'create'} scheduled task {a.get('name')}")
async def save_task(ctx: ActionContext) -> dict[str, Any]:
    cog = _scheduler(ctx)
    guild = guild_of(ctx)
    name = ctx.text("name", max_length=100).strip()
    cron = ctx.text("cron", max_length=120).strip()
    kind = ctx.text("type", max_length=10)
    if not name:
        raise ActionError("Give the task a name.")
    if error := CronExpression.validate(cron):
        raise ActionError(f"The schedule is not valid: {error}")
    payload, channel_id = _payload(ctx, kind, guild)
    max_runs = ctx.integer("max_runs", default=0, minimum=0, maximum=100000) or None
    if ctx.args.get("id"):
        task = _find_task(ctx, cog)
        task.update(task_name=name, cron_expression=cron, task_type=kind, payload=payload, channel_id=channel_id,
                    guild_id=guild.id, max_runs=max_runs)
        task["next_run"] = cog._next(task, dt.datetime.now(cog.tz))
        await cog._save(task)
        return {"task": _task(cog, ctx.bot, task)}
    if len(cog.get_tasks(guild.id)) >= ctx.bot.config.settings.scheduler.max_tasks_per_guild:
        raise ActionError("This server has the maximum number of tasks.")
    task_id = await cog.create_task_programmatic(name, cron, kind, guild_id=guild.id, channel_id=channel_id,
                                                 creator_id=0, payload=payload, max_runs=max_runs)
    if task_id is None:
        raise ActionError("The task could not be created.")
    return {"task": _task(cog, ctx.bot, cog.tasks[task_id])}


@action("scheduler.toggle", "scheduler", timeout=20)
async def toggle_task(ctx: ActionContext) -> dict[str, Any]:
    cog = _scheduler(ctx)
    task = _find_task(ctx, cog)
    await cog.set_enabled(task["task_id"], ctx.flag("enabled"))
    return {"task": _task(cog, ctx.bot, task)}


@action("scheduler.run", "scheduler", timeout=60, summary=lambda a: f"run scheduled task {a.get('id')} now")
async def run_task(ctx: ActionContext) -> dict[str, Any]:
    cog = _scheduler(ctx)
    task = _find_task(ctx, cog)
    ok = await cog.execute(task, manual=True)
    return {"ok": ok, "task": _task(cog, ctx.bot, task)}


@action("scheduler.delete", "scheduler", timeout=20, summary=lambda a: f"delete scheduled task {a.get('id')}")
async def delete_task(ctx: ActionContext) -> dict[str, Any]:
    cog = _scheduler(ctx)
    task = _find_task(ctx, cog)
    await cog.delete_task_programmatic(task["task_id"])
    return {"deleted": task["task_id"]}
