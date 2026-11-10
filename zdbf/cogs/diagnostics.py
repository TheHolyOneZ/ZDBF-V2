# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import importlib.util
import logging
import os
import platform
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord
import psutil
from discord import app_commands
from discord.ext import commands

from .. import __version__
from ..core.database import utcnow_iso
from ..core.permissions import owner_only
from ..core.storage import global_file_handler
from ..ui import BaseView, Paginator, Status, button, cards, row
from ..utils import human_bytes, human_duration

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot

log = logging.getLogger("zdbf.diagnostics")

SPARK = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    return "".join(SPARK[min(len(SPARK) - 1, int((v - lo) / span * (len(SPARK) - 1)))] for v in values)


@dataclass
class HealthSnapshot:
    timestamp: float
    status: str
    error_rate: float
    loop_lag_ms: float
    latency_ms: float
    memory_mb: float
    commands: int
    errors: int


class DiagnosticsView(BaseView):
    def __init__(self, cog: Diagnostics, author_id: int) -> None:
        super().__init__(author_id=author_id, timeout=600)
        self.cog = cog

    def build(self) -> None:
        self.clear_items()
        box = self.cog.overview_card()

        async def refresh(interaction: discord.Interaction[Any]) -> None:
            await self.refresh(interaction)

        async def run_check(interaction: discord.Interaction[Any]) -> None:
            await self.cog.health_check()
            await self.refresh(interaction)

        box.add_item(row(button("Refresh", refresh),
                         button("Run health check", run_check)))
        self.add_item(box)


class Diagnostics(commands.Cog, name="Diagnostics"):
    """Health, event-loop lag, error tracking and slash command budget."""

    KV_HISTORY = "diagnostics.history"

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.process = psutil.Process(os.getpid())
        self.lag_samples: deque[float] = deque(maxlen=60)
        self.history: deque[HealthSnapshot] = deque(maxlen=96)
        self.status = "starting"
        self._tasks: list[asyncio.Task[Any]] = []
        self._last_lag_alert = 0.0

    @property
    def settings(self) -> Any:
        return self.bot.config.settings.diagnostics

    async def cog_load(self) -> None:
        for raw in await self.bot.db.kv_get(self.KV_HISTORY, []):
            with contextlib.suppress(TypeError):
                self.history.append(HealthSnapshot(**raw))
        self.process.cpu_percent(None)
        self._tasks = [asyncio.create_task(self._lag_loop()), asyncio.create_task(self._health_loop())]

    async def cog_unload(self) -> None:
        for task in self._tasks:
            task.cancel()
        await self._persist()

    @property
    def loop_lag_ms(self) -> float:
        return sum(self.lag_samples) / len(self.lag_samples) if self.lag_samples else 0.0

    async def _lag_loop(self) -> None:
        interval = 1.0
        while True:
            start = time.perf_counter()
            await asyncio.sleep(interval)
            lag = max(0.0, (time.perf_counter() - start - interval) * 1000)
            self.lag_samples.append(lag)
            threshold = self.settings.loop_lag_threshold_ms
            if len(self.lag_samples) >= 10 and self.loop_lag_ms > threshold and time.time() - self._last_lag_alert > 300:
                self._last_lag_alert = time.time()
                await self.bot.alerts.send("diagnostics", f"Event loop lag {self.loop_lag_ms:.0f} ms "
                                                          f"(threshold {threshold} ms)", "warning")

    async def _health_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                await self.health_check()
            except Exception:
                log.exception("health check failed")
            await asyncio.sleep(self.settings.health_interval_minutes * 60)

    async def health_check(self) -> HealthSnapshot:
        m = self.bot.metrics
        rate = m.error_rate()
        lag = self.loop_lag_ms
        warn = self.settings.error_rate_warn_percent
        status = "healthy"
        if rate >= warn * 2 or lag > self.settings.loop_lag_threshold_ms * 2:
            status = "critical"
        elif rate >= warn or lag > self.settings.loop_lag_threshold_ms:
            status = "degraded"
        latency = self.bot.latency * 1000 if self.bot.latency == self.bot.latency else -1
        snap = HealthSnapshot(time.time(), status, rate, round(lag, 2), round(latency, 1),
                              round(self.process.memory_info().rss / 1048576, 1), m.commands_total, m.errors_total)
        if status != "healthy" and self.status != status:
            await self.bot.alerts.send("diagnostics", f"Health is **{status}** - error rate {rate:.1f}%, "
                                                      f"loop lag {lag:.0f} ms", "error" if status == "critical" else "warning")
        self.status = status
        self.history.append(snap)
        await self._persist()
        await global_file_handler.atomic_write_json("data/diagnostics.json", self.report())
        return snap

    async def _persist(self) -> None:
        await self.bot.db.kv_set(self.KV_HISTORY, [asdict(h) for h in list(self.history)[-96:]])

    def report(self) -> dict[str, Any]:
        bot = self.bot
        return {
            "generated_at": utcnow_iso(),
            "version": __version__,
            "status": self.status,
            "uptime_seconds": round(bot.metrics.uptime),
            "bot": {"user": str(bot.user), "id": bot.user.id if bot.user else None,
                    "latency_ms": round(bot.latency * 1000, 2)},
            "environment": {"python": platform.python_version(), "discord_py": discord.__version__,
                            "platform": platform.platform()},
            "extensions": {"loaded": sorted(bot.extensions), "failed": bot.ext.failed,
                           "load_times_ms": bot.ext.load_times},
            "commands": {"prefix_total": len(list(bot.walk_commands())), **bot.slash_command_count()},
            "guilds": len(bot.guilds),
            "metrics": bot.metrics.get_stats(),
            "loop_lag_ms": round(self.loop_lag_ms, 2),
            "hooks": bot.hooks.metrics,
        }

    def overview_card(self) -> discord.ui.Container[Any]:
        bot = self.bot
        m = bot.metrics
        with self.process.oneshot():
            mem = self.process.memory_info().rss
            cpu = self.process.cpu_percent(None)
            threads = self.process.num_threads()
            try:
                files = len(self.process.open_files())
            except (psutil.Error, OSError):
                files = -1
        sys_mem = psutil.virtual_memory()
        accent = {"healthy": "success", "degraded": "warning", "critical": "error"}.get(self.status, "primary")
        state = {"healthy": Status.OK, "degraded": Status.WARN, "critical": Status.ERROR}.get(self.status, "⚪")
        lag_hist = [s.loop_lag_ms for s in list(self.history)[-24:]]
        budget = bot.slash_command_count()
        return cards.card(
            "Framework diagnostics",
            f"{state} Status: **{self.status}** · uptime {human_duration(m.uptime)}",
            cards.sep(),
            "**Performance**\n" + cards.kv({
                "Event loop lag": f"{self.loop_lag_ms:.1f} ms (threshold {self.settings.loop_lag_threshold_ms} ms)",
                "Gateway latency": f"{bot.latency * 1000:.0f} ms",
                "Error rate (1h)": f"{m.error_rate():.1f}%",
                "Commands / errors": f"{m.commands_total:,} / {m.errors_total:,}",
            }) + (f"\nLag trend `{sparkline(lag_hist)}`" if len(lag_hist) > 1 else ""),
            cards.sep(),
            "**Process**\n" + cards.kv({
                "Memory": f"{human_bytes(mem)} (system {sys_mem.percent:.0f}% used)",
                "CPU": f"{cpu:.1f}%", "Threads": threads, "Open files": files if files >= 0 else "n/a",
            }),
            cards.sep(),
            "**Framework**\n" + cards.kv({
                "Extensions": f"{len(bot.extensions)} loaded · {len(bot.ext.failed)} failed",
                "Hooks": f"{len(bot.hooks.all_hooks())} registered · queue {bot.hooks.queue_size}",
                "Slash commands": f"{budget['top_level']}/100 top-level",
                "Servers": f"{len(bot.guilds):,}",
            }),

            accent=accent,
            foot=f"ZDBF {__version__} · Python {platform.python_version()} · discord.py {discord.__version__}",
        )

    @commands.hybrid_group(name="diag", description="Framework diagnostics (bot owner)", invoke_without_command=True)
    @owner_only()
    async def diag(self, ctx: commands.Context[ZDBFBot]) -> None:
        await self.diag_overview.callback(self, ctx)  # type: ignore[arg-type]

    @diag.command(name="overview", description="Live health dashboard")
    async def diag_overview(self, ctx: commands.Context[ZDBFBot]) -> None:
        await DiagnosticsView(self, ctx.author.id).send(ctx)

    @diag.command(name="history", description="Health check history")
    async def diag_history(self, ctx: commands.Context[ZDBFBot]) -> None:
        snaps = list(self.history)
        if not snaps:
            await ctx.send(view=cards.info("No history yet", "Health checks run every "
                                           f"{self.settings.health_interval_minutes} minutes."))
            return
        icon = {"healthy": Status.OK, "degraded": Status.WARN, "critical": Status.ERROR}
        lines = [
            f"{icon.get(s.status, '⚪')} {cards.timestamp(s.timestamp, 'f')} · err {s.error_rate:.1f}% · "
            f"lag {s.loop_lag_ms:.0f} ms · ping {s.latency_ms:.0f} ms · {s.memory_mb:.0f} MB"
            for s in reversed(snaps)
        ]
        trend = (f"Error rate `{sparkline([s.error_rate for s in snaps[-30:]])}`\n"
                 f"Loop lag  `{sparkline([s.loop_lag_ms for s in snaps[-30:]])}`\n"
                 f"Memory    `{sparkline([s.memory_mb for s in snaps[-30:]])}`")
        pages = [[trend, cards.sep(), page] for page in Paginator.from_lines(lines, per_page=12, title="").pages]
        await Paginator(pages, title="Health history", subtitle=f"{len(snaps)} snapshots").send(ctx)

    @diag.command(name="errors", description="Recent command errors")
    async def diag_errors(self, ctx: commands.Context[ZDBFBot]) -> None:
        errs = list(self.bot.metrics.recent_errors)
        lines = [
            f"{cards.timestamp(e.timestamp)} **{e.command}** · <@{e.user_id}>"
            + (f" · guild `{e.guild_id}`" if e.guild_id else "") + f"\n```{cards.truncate(e.error, 180)}```"
            for e in reversed(errs)
        ]
        await Paginator.from_lines(lines or [f"{Status.OK} No errors recorded this session."], per_page=5,
                                   title="Recent errors", accent="error" if errs else "success",
                                   subtitle=f"{self.bot.metrics.errors_total} total · "
                                            f"{self.bot.metrics.error_rate():.1f}% in the last hour").send(ctx)

    @diag.command(name="alerts", description="Set the channel for diagnostics alerts")
    async def diag_alerts(self, ctx: commands.Context[ZDBFBot], channel: discord.TextChannel | None = None) -> None:
        await self.bot.alerts.set_channel("diagnostics", channel.id if channel else None)
        await ctx.send(view=cards.success("Diagnostics alerts", f"→ {channel.mention if channel else '*cleared*'}"))

    @diag.command(name="commands", description="Slash command budget (Discord allows 100 top-level commands)")
    async def diag_commands(self, ctx: commands.Context[ZDBFBot]) -> None:
        budget = self.bot.slash_command_count()
        rows = []
        for cmd in sorted(self.bot.tree.get_commands(type=discord.AppCommandType.chat_input), key=lambda c: c.name):
            subs = sum(1 for _ in cmd.walk_commands()) if isinstance(cmd, app_commands.Group) else 0
            rows.append(f"`/{cmd.name}`" + (f" · {subs} subcommands" if subs else ""))
        dev = self.bot.config.settings.bot.dev_guild_ids
        head = (f"{cards.bar(budget['top_level'], 100)}\n**{budget['top_level']}**/100 top-level · "
                f"**{budget['with_subcommands']}** incl. subcommands"
                + (f"\n-# Owner groups are scoped to {len(dev)} development server(s)." if dev else ""))
        demoted = sorted(self.bot.slash_guard.demoted.values(), key=lambda d: (d.scope, d.name))
        if demoted:
            head += (f"\n{Status.WARN} **{len(demoted)}** command(s) are over the limit and work with the prefix only "
                     "(framework commands are always kept; extensions keep their slots in load order).")
        pages = [[head, cards.sep(), p] for p in Paginator.from_lines(rows, per_page=20, title="").pages]
        if demoted:
            lines = [f"{Status.WARN if d.fallback else Status.ERROR} `{d.name}` · {d.kind} · {d.scope} · "
                     f"`{d.source or '?'}`" + ("" if d.fallback else " · *no prefix fallback (name taken)*")
                     for d in demoted]
            pages += [["**Prefix-only commands**", p] for p in Paginator.from_lines(lines, per_page=15, title="").pages]
        await Paginator(pages, title="Slash command budget").send(ctx)

    @diag.command(name="migrations", description="Database migration status")
    async def diag_migrations(self, ctx: commands.Context[ZDBFBot]) -> None:
        mig: Migrations | None = self.bot.get_cog("Database Migrations")  # type: ignore[assignment]
        core = await self.bot.db.fetchall("SELECT version, name, applied_at FROM _zdbf_schema ORDER BY version")
        lines = ["**Framework schema**"] + [f"{Status.OK} `{r['version']:04d}` {r['name']} · {r['applied_at']}" for r in core]
        if mig is not None:
            status = await mig.status()
            lines += ["", f"**User migrations** (`{mig.directory}/`)"]
            for item in status:
                icon = Status.OK if item["applied"] else Status.ERROR if item.get("failed") else Status.OFF
                lines.append(f"{icon} `{item['number']:03d}` {item['name']} - {item['description'] or ''}")
            if not status:
                lines.append("*No migration files.*")
        await Paginator.from_lines(lines, per_page=20, title="Migrations").send(ctx)

    @diag.command(name="migrate", description="Apply pending user migrations")
    async def diag_migrate(self, ctx: commands.Context[ZDBFBot]) -> None:
        mig: Migrations | None = self.bot.get_cog("Database Migrations")  # type: ignore[assignment]
        if mig is None:
            await ctx.send(view=cards.error("Unavailable", "The migrations system is not loaded."))
            return
        applied, failed = await mig.run_pending()
        body = "\n".join([f"{Status.OK} {n}" for n in applied] + [f"{Status.ERROR} {n}" for n in failed]) or "Nothing pending."
        await ctx.send(view=(cards.success if not failed else cards.error)("Migrations", body))


class Migrations(commands.Cog, name="Database Migrations"):
    """User/extension migrations from ``./migrations/NNN_name.py`` (V1 format)."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.directory = Path("migrations")
        self._applied: set[int] = set()

    async def cog_load(self) -> None:
        await self.bot.db.execute(
            "CREATE TABLE IF NOT EXISTS _schema_migrations (migration_number INTEGER PRIMARY KEY, name TEXT NOT NULL,"
            " description TEXT, applied_at TEXT, success INTEGER DEFAULT 1)"
        )
        await self.run_pending()

    def discover(self) -> list[tuple[int, str, Path]]:
        self.directory.mkdir(exist_ok=True)
        found = []
        for path in sorted(self.directory.glob("*.py")):
            number, _, name = path.stem.partition("_")
            if number.isdigit() and name:
                found.append((int(number), name, path))
        return found

    @staticmethod
    def _load(path: Path) -> Any:
        spec = importlib.util.spec_from_file_location(f"zdbf_migration_{path.stem}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    async def _applied_numbers(self) -> dict[int, bool]:
        rows = await self.bot.db.fetchall("SELECT migration_number, success FROM _schema_migrations")
        return {r[0]: bool(r[1]) for r in rows}

    async def run_pending(self) -> tuple[list[str], list[str]]:
        done = await self._applied_numbers()
        applied, failed = [], []
        pending = [m for m in self.discover() if not done.get(m[0])]
        if pending and not self.bot.db.memory:
            try:
                await self.bot.db.backup(label=f"pre-user-{pending[0][0]:03d}")
            except Exception:
                log.exception("pre-migration backup failed")
        for number, name, path in pending:
            label = f"{number:03d}_{name}"
            module: Any = None
            try:
                module = self._load(path)
                await module.up(self.bot.db)
                await self.bot.db.conn.commit()
                ok = True
                applied.append(label)
                log.info("applied migration %s", label)
            except Exception as exc:
                ok = False
                failed.append(f"{label}: {exc}")
                log.exception("migration %s failed", label)
                await self.bot.alerts.send("diagnostics", f"Migration `{label}` failed: {exc}", "error")
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO _schema_migrations (migration_number, name, description, applied_at, success)"
                " VALUES (?, ?, ?, ?, ?)",
                (number, name, getattr(module, "description", None), dt.datetime.now(dt.UTC).isoformat(),
                 int(ok)),
            )
            if not ok:
                break
        self._applied = {n for n, ok in (await self._applied_numbers()).items() if ok}
        return applied, failed

    def is_migration_applied(self, number: int) -> bool:
        return number in self._applied

    async def status(self) -> list[dict[str, Any]]:
        done = await self._applied_numbers()
        out = []
        for number, name, path in self.discover():
            description = None
            with contextlib.suppress(Exception):
                description = getattr(self._load(path), "description", None)
            out.append({"number": number, "name": name, "description": description,
                        "applied": done.get(number) is True, "failed": done.get(number) is False})
        return out


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(Diagnostics(bot))
    await bot.add_cog(Migrations(bot))
