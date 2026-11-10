# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import logging
import secrets
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from ..core.cron import CronExpression
from ..core.database import utcnow_iso
from ..core.permissions import admin_or_owner
from ..ui import BaseView, Paginator, Status, button, cards, confirm, row

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot

log = logging.getLogger("zdbf.scheduler")

TaskType = Literal["message", "hook", "log"]


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    with contextlib.suppress(ValueError):
        parsed = dt.datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return None


class TaskView(BaseView):
    def __init__(self, cog: Scheduler, task: dict[str, Any], author_id: int) -> None:
        super().__init__(author_id=author_id)
        self.cog = cog
        self.task = task
        self.note: str | None = None

    def build(self) -> None:
        self.clear_items()
        box = self.cog.task_card(self.task)
        if self.note:
            box.add_item(cards.text(self.note))

        async def toggle(interaction: discord.Interaction[Any]) -> None:
            await self.cog.set_enabled(self.task["task_id"], not self.task["enabled"])
            self.task = self.cog.tasks[self.task["task_id"]]
            await self.refresh(interaction)

        async def run_now(interaction: discord.Interaction[Any]) -> None:
            await interaction.response.defer()
            ok = await self.cog.execute(self.task, manual=True)
            self.note = f"{Status.OK} Ran now." if ok else f"{Status.ERROR} Run failed - check the logs."
            await self.refresh(interaction)

        async def delete(interaction: discord.Interaction[Any]) -> None:
            await self.cog.delete_task_programmatic(self.task["task_id"])
            self.clear_items()
            self.add_item(cards.card("Task deleted", f"`{self.task['task_name']}` was removed.", accent="muted"))
            await interaction.response.edit_message(view=self)
            self.stop()

        box.add_item(row(
            button("Disable" if self.task["enabled"] else "Enable", toggle),
            button("Run now", run_now),
            button("Delete", delete, style=discord.ButtonStyle.danger),
        ))
        self.add_item(box)


class Scheduler(commands.Cog, name="Task Scheduler"):
    """Run messages, hooks and log entries on a cron schedule."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.tasks: dict[str, dict[str, Any]] = {}
        self._runner: asyncio.Task[None] | None = None
        self._jobs: set[asyncio.Task[bool]] = set()

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.bot.config.settings.scheduler.timezone)

    async def cog_load(self) -> None:
        rows = await self.bot.db.fetchall("SELECT * FROM scheduled_tasks")
        for r in rows:
            task = dict(r)
            task["enabled"] = bool(task["enabled"])
            task["payload"] = json.loads(task["payload"] or "{}")
            self.tasks[task["task_id"]] = task
        now = dt.datetime.now(self.tz)
        for task in self.tasks.values():
            nxt = _parse_ts(task.get("next_run"))
            if nxt is None or nxt < now - dt.timedelta(minutes=5):
                task["next_run"] = self._next(task, now)
        self._runner = asyncio.create_task(self._loop(), name="zdbf-scheduler")

    async def cog_unload(self) -> None:
        if self._runner:
            self._runner.cancel()

    def _next(self, task: dict[str, Any], after: dt.datetime) -> str | None:
        try:
            nxt = CronExpression.parse(task["cron_expression"]).next_after(after.astimezone(self.tz))
        except ValueError:
            return None
        return nxt.isoformat() if nxt else None

    async def _loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            now = dt.datetime.now(self.tz)
            await asyncio.sleep(60 - now.second - now.microsecond / 1e6 + 0.05)
            now = dt.datetime.now(self.tz)
            for task in list(self.tasks.values()):
                if not task["enabled"]:
                    continue
                nxt = _parse_ts(task.get("next_run"))
                if nxt is not None and nxt <= now:
                    task["next_run"] = self._next(task, now)
                    job = asyncio.create_task(self.execute(task))
                    self._jobs.add(job)
                    job.add_done_callback(self._jobs.discard)

    async def execute(self, task: dict[str, Any], *, manual: bool = False) -> bool:
        ok = True
        try:
            match task["task_type"]:
                case "message":
                    await self._run_message(task)
                case "hook":
                    payload = task["payload"]
                    data = dict(payload.get("data", {}))
                    data.update(_task_name=task["task_name"], _task_id=task["task_id"])
                    await self.bot.hooks.emit(payload.get("hook_name", "scheduled_task"), **data)
                case "log":
                    level = str(task["payload"].get("level", "INFO")).upper()
                    log.log(getattr(logging, level, logging.INFO), "[scheduled] %s",
                            task["payload"].get("message", f"task {task['task_name']} fired"))
                case other:
                    raise ValueError(f"unknown task type {other!r}")
        except Exception as exc:
            ok = False
            log.exception("scheduled task %s failed", task["task_name"])
            await self.bot.alerts.send("scheduler", f"Task `{task['task_name']}` failed: {exc}", "error")
        now = dt.datetime.now(self.tz)
        task["last_run"] = now.isoformat()
        task["run_count"] = task.get("run_count", 0) + 1
        if task.get("max_runs") and task["run_count"] >= task["max_runs"]:
            task["enabled"] = False
        await self._save(task)
        await self.bot.hooks.emit("scheduled_task", task_id=task["task_id"], task_name=task["task_name"], ok=ok)
        return ok

    async def _run_message(self, task: dict[str, Any]) -> None:
        channel = self.bot.get_channel(int(task["channel_id"] or 0))
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError(f"channel {task['channel_id']} not found")
        payload = task["payload"]
        content = payload.get("content", "")
        if payload.get("embed"):
            await channel.send(content=content or None, embed=discord.Embed.from_dict(payload["embed"]))
        elif payload.get("title") or payload.get("card", True):
            view = cards.static(cards.card(payload.get("title"), content or "​",
                                           accent=payload.get("accent", "primary"),
                                           foot=payload.get("footer")))
            await channel.send(view=view, allowed_mentions=discord.AllowedMentions(everyone=False, roles=True))
        else:
            await channel.send(content, allowed_mentions=discord.AllowedMentions(everyone=False, roles=True))

    async def _save(self, task: dict[str, Any]) -> None:
        task["updated_at"] = utcnow_iso()
        self.tasks[task["task_id"]] = task
        await self.bot.db.execute(
            "INSERT INTO scheduled_tasks (task_id, guild_id, channel_id, creator_id, task_name, task_type, "
            "cron_expression, payload, enabled, last_run, next_run, run_count, max_runs, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET "
            "channel_id = excluded.channel_id, task_name = excluded.task_name, task_type = excluded.task_type, "
            "cron_expression = excluded.cron_expression, payload = excluded.payload, enabled = excluded.enabled, "
            "last_run = excluded.last_run, next_run = excluded.next_run, run_count = excluded.run_count, "
            "max_runs = excluded.max_runs, updated_at = excluded.updated_at",
            (task["task_id"], task.get("guild_id"), task.get("channel_id"), task.get("creator_id", 0),
             task["task_name"], task["task_type"], task["cron_expression"], json.dumps(task["payload"]),
             int(task["enabled"]), task.get("last_run"), task.get("next_run"), task.get("run_count", 0),
             task.get("max_runs"), task.get("created_at") or utcnow_iso(), task["updated_at"]),
        )

    async def create_task_programmatic(
        self,
        task_name: str,
        cron_expression: str,
        task_type: str = "log",
        guild_id: int | None = None,
        channel_id: int | None = None,
        creator_id: int = 0,
        payload: dict[str, Any] | None = None,
        max_runs: int | None = None,
        enabled: bool = True,
    ) -> str | None:
        if CronExpression.validate(cron_expression) or task_type not in ("message", "hook", "log"):
            return None
        task = {
            "task_id": secrets.token_hex(4),
            "guild_id": guild_id, "channel_id": channel_id, "creator_id": creator_id,
            "task_name": task_name[:100], "task_type": task_type, "cron_expression": cron_expression.strip(),
            "payload": payload or {}, "enabled": enabled, "last_run": None, "run_count": 0,
            "max_runs": max_runs, "created_at": utcnow_iso(),
        }
        task["next_run"] = self._next(task, dt.datetime.now(self.tz))
        await self._save(task)
        return task["task_id"]

    async def delete_task_programmatic(self, task_id: str) -> bool:
        existed = self.tasks.pop(task_id, None) is not None
        await self.bot.db.execute("DELETE FROM scheduled_tasks WHERE task_id = ?", (task_id,))
        return existed

    async def set_enabled(self, task_id: str, enabled: bool) -> bool:
        task = self.tasks.get(task_id)
        if task is None:
            return False
        task["enabled"] = enabled
        if enabled:
            task["next_run"] = self._next(task, dt.datetime.now(self.tz))
        await self._save(task)
        return True

    def get_tasks(self, guild_id: int | None = None) -> list[dict[str, Any]]:
        return sorted((t for t in self.tasks.values() if guild_id is None or t.get("guild_id") == guild_id),
                      key=lambda t: t["task_name"].lower())

    def task_card(self, task: dict[str, Any]) -> discord.ui.Container[Any]:
        expr = CronExpression.parse(task["cron_expression"])
        nxt = _parse_ts(task.get("next_run"))
        last = _parse_ts(task.get("last_run"))
        payload = task["payload"]
        target = f"<#{task['channel_id']}>" if task.get("channel_id") else "-"
        summary = {
            "message": f"Posts in {target}: {cards.truncate(payload.get('content', ''), 200)}",
            "hook": f"Emits hook `{payload.get('hook_name', 'scheduled_task')}`",
            "log": f"Logs: {cards.truncate(payload.get('message', ''), 200)}",
        }.get(task["task_type"], "?")
        upcoming = ", ".join(cards.timestamp(d, "f") for d in expr.upcoming(dt.datetime.now(self.tz), 3))
        return cards.card(
            task["task_name"],
            summary,
            cards.sep(),
            cards.kv({
                "Schedule": f"{expr.describe()} · `{task['cron_expression']}` ({self.tz.key})",
                "Status": "enabled" if task["enabled"] else "disabled",
                "Next run": cards.timestamp(nxt) if nxt and task["enabled"] else "-",
                "Last run": cards.timestamp(last) if last else "never",
                "Runs": f"{task.get('run_count', 0)}" + (f" / {task['max_runs']}" if task.get("max_runs") else ""),
                "Created by": f"<@{task['creator_id']}>" if task.get("creator_id") else "an extension",
                "ID": f"`{task['task_id']}`",
            }),
            f"-# Upcoming: {upcoming}" if upcoming and task["enabled"] else None,

            accent="primary" if task["enabled"] else "muted",
        )

    async def _task_ac(self, interaction: discord.Interaction[Any], current: str) -> list[app_commands.Choice[str]]:
        tasks = self.get_tasks(interaction.guild_id)
        return [app_commands.Choice(name=f"{t['task_name']} ({t['task_id']})"[:100], value=t["task_id"])
                for t in tasks if current.lower() in t["task_name"].lower() or current in t["task_id"]][:25]

    def _find(self, guild_id: int | None, ref: str) -> dict[str, Any] | None:
        tasks = self.get_tasks(guild_id)
        return next((t for t in tasks if t["task_id"] == ref), None) or next(
            (t for t in tasks if t["task_name"].lower() == ref.lower()), None)

    @commands.hybrid_group(name="schedule", description="Scheduled tasks", invoke_without_command=True)
    @commands.guild_only()
    @admin_or_owner()
    async def schedule(self, ctx: commands.Context[ZDBFBot]) -> None:
        await self.schedule_list.callback(self, ctx)  # type: ignore[arg-type]

    @schedule.command(name="create", description="Create a scheduled task")
    @app_commands.describe(
        name="A name for the task", cron="Cron expression, e.g. '0 9 * * mon' or '@daily'",
        task_type="What the task does", channel="Channel for message tasks",
        message="Message text (message tasks) or log line (log tasks)",
        hook_name="Hook to emit (hook tasks)", max_runs="Disable after this many runs",
    )
    @commands.guild_only()
    @admin_or_owner()
    async def schedule_create(self, ctx: commands.Context[ZDBFBot], name: str, cron: str,
                              task_type: TaskType = "message", channel: discord.TextChannel | None = None,
                              message: str | None = None, hook_name: str | None = None,
                              max_runs: app_commands.Range[int, 1, 100000] | None = None) -> None:
        assert ctx.guild is not None
        if err := CronExpression.validate(cron):
            await ctx.send(view=cards.error("Invalid cron expression", f"`{cron}` - {err}\n"
                                            "Format: `minute hour day month weekday`, e.g. `30 18 * * fri`."))
            return
        if len(self.get_tasks(ctx.guild.id)) >= self.bot.config.settings.scheduler.max_tasks_per_guild:
            await ctx.send(view=cards.error("Limit reached", "This server has the maximum number of tasks."))
            return
        payload: dict[str, Any]
        match task_type:
            case "message":
                channel = channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
                if channel is None or not message:
                    await ctx.send(view=cards.error("Missing options", "Message tasks need a channel and a message."))
                    return
                if not channel.permissions_for(ctx.guild.me).send_messages:
                    await ctx.send(view=cards.error("No access", f"I can't send messages in {channel.mention}."))
                    return
                payload = {"content": message, "title": None}
            case "hook":
                payload = {"hook_name": hook_name or "scheduled_task", "data": {"guild_id": ctx.guild.id}}
            case _:
                payload = {"message": message or f"task {name} fired", "level": "INFO"}
        task_id = await self.create_task_programmatic(
            name, cron, task_type, guild_id=ctx.guild.id, channel_id=channel.id if channel else None,
            creator_id=ctx.author.id, payload=payload, max_runs=max_runs)
        assert task_id is not None
        await TaskView(self, self.tasks[task_id], ctx.author.id).send(ctx)

    @schedule.command(name="list", description="Tasks in this server")
    @commands.guild_only()
    @admin_or_owner()
    async def schedule_list(self, ctx: commands.Context[ZDBFBot]) -> None:
        tasks = self.get_tasks(ctx.guild.id if ctx.guild else None)
        lines = []
        for t in tasks:
            nxt = _parse_ts(t.get("next_run"))
            state = Status.OK if t["enabled"] else Status.OFF
            lines.append(f"{state} **{t['task_name']}** `{t['task_id']}` · {t['task_type']}\n"
                         f"-# {CronExpression.parse(t['cron_expression']).describe()}"
                         + (f" · next {cards.timestamp(nxt)}" if nxt and t["enabled"] else ""))
        await Paginator.from_lines(lines or ["*No tasks yet - create one with `/schedule create`.*"], per_page=8,
                                   title="Scheduled tasks",
                                   subtitle=f"{len(tasks)} task(s) · timezone {self.tz.key}").send(ctx)

    @schedule.command(name="info", description="Show and manage a task")
    @app_commands.autocomplete(task=_task_ac)
    @commands.guild_only()
    @admin_or_owner()
    async def schedule_info(self, ctx: commands.Context[ZDBFBot], *, task: str) -> None:
        found = self._find(ctx.guild.id if ctx.guild else None, task)
        if found is None:
            await ctx.send(view=cards.error("Unknown task", f"No task `{task}` in this server."))
            return
        await TaskView(self, found, ctx.author.id).send(ctx)

    @schedule.command(name="toggle", description="Enable or disable a task")
    @app_commands.autocomplete(task=_task_ac)
    @commands.guild_only()
    @admin_or_owner()
    async def schedule_toggle(self, ctx: commands.Context[ZDBFBot], *, task: str) -> None:
        found = self._find(ctx.guild.id if ctx.guild else None, task)
        if found is None:
            await ctx.send(view=cards.error("Unknown task", f"No task `{task}` in this server."))
            return
        await self.set_enabled(found["task_id"], not found["enabled"])
        await ctx.send(view=cards.success(f"Task {'enabled' if found['enabled'] else 'disabled'}",
                                          f"`{found['task_name']}`"))

    @schedule.command(name="delete", description="Delete a task")
    @app_commands.autocomplete(task=_task_ac)
    @commands.guild_only()
    @admin_or_owner()
    async def schedule_delete(self, ctx: commands.Context[ZDBFBot], *, task: str) -> None:
        found = self._find(ctx.guild.id if ctx.guild else None, task)
        if found is None:
            await ctx.send(view=cards.error("Unknown task", f"No task `{task}` in this server."))
            return
        view = await confirm(ctx, "Delete task?", f"`{found['task_name']}` will stop running.", confirm_label="Delete")
        if view.value:
            await self.delete_task_programmatic(found["task_id"])

    @schedule.command(name="preview", description="Explain a cron expression and show its next runs")
    async def schedule_preview(self, ctx: commands.Context[ZDBFBot], *, cron: str) -> None:
        try:
            expr = CronExpression.parse(cron)
        except ValueError as exc:
            await ctx.send(view=cards.error("Invalid cron expression", str(exc)))
            return
        runs = "\n".join(f"• {cards.timestamp(d, 'F')} ({cards.timestamp(d)})"
                         for d in expr.upcoming(dt.datetime.now(self.tz), 5))
        await ctx.send(view=cards.info(expr.describe(), f"`{cron}` in **{self.tz.key}**\n\n{runs or 'Never runs.'}"))

    @schedule.command(name="alerts", description="Channel for failed-task alerts")
    @commands.guild_only()
    @admin_or_owner()
    async def schedule_alerts(self, ctx: commands.Context[ZDBFBot], channel: discord.TextChannel | None = None) -> None:
        if not await self.bot.is_owner(ctx.author):
            await ctx.send(view=cards.error("Owner only", "Alert routing is global - ask the bot owner."))
            return
        await self.bot.alerts.set_channel("scheduler", channel.id if channel else None)
        await ctx.send(view=cards.success("Scheduler alerts", f"→ {channel.mention if channel else '*cleared*'}"))


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(Scheduler(bot))
