# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..core.permissions import owner_only
from ..ui import ListDetailView, Paginator, Status, button, cards, row
from ..utils import human_duration
from .diagnostics import sparkline

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot


@dataclass
class ShardMetrics:
    shard_id: int
    latencies: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    events: Counter[str] = field(default_factory=Counter)
    last_event: float = field(default_factory=time.time)
    connects: int = 0
    disconnects: int = 0
    resumes: int = 0
    last_connect: float | None = None
    last_disconnect: float | None = None
    started: float = field(default_factory=time.time)
    downtime: float = 0.0
    down_since: float | None = None
    failures: int = 0
    messages: int = 0
    commands: int = 0
    alerted: bool = False

    def connected(self) -> None:
        self.connects += 1
        self.last_connect = time.time()
        if self.down_since:
            self.downtime += time.time() - self.down_since
            self.down_since = None

    def disconnected(self) -> None:
        self.disconnects += 1
        self.last_disconnect = time.time()
        self.down_since = self.down_since or time.time()

    def event(self, name: str) -> None:
        self.events[name] += 1
        self.last_event = time.time()

    @property
    def latency_ms(self) -> float:
        return self.latencies[-1] if self.latencies else 0.0

    @property
    def avg_ms(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0.0

    @property
    def uptime_pct(self) -> float:
        total = time.time() - self.started
        down = self.downtime + (time.time() - self.down_since if self.down_since else 0)
        return 100.0 if total <= 0 else max(0.0, (total - down) / total * 100)

    def health(self) -> tuple[bool, str]:
        if self.down_since:
            return False, f"disconnected for {human_duration(time.time() - self.down_since)}"
        if self.avg_ms > 1000:
            return False, f"high latency ({self.avg_ms:.0f} ms avg)"
        if self.last_disconnect and time.time() - self.last_disconnect < 60:
            return False, "reconnected less than a minute ago"
        return True, "healthy"


class MonitorView(ListDetailView[int]):
    title = "Shard monitor"
    placeholder = "Inspect a shard"
    per_page = 15

    def __init__(self, cog: ShardMonitor, author_id: int) -> None:
        super().__init__(sorted(cog.metrics), author_id=author_id)
        self.cog = cog

    def item_key(self, item: int) -> str:
        return str(item)

    def item_line(self, item: int) -> str:
        metric = self.cog.m(item)
        ok, reason = metric.health()
        return (f"{Status.OK if ok else Status.ERROR} **Shard {item}**  `{metric.latency_ms:.0f} ms` · "
                f"{self.cog.guild_counts().get(item, 0)} servers · {metric.uptime_pct:.2f}% up"
                + ("" if ok else f" · {reason}"))

    def item_option(self, item: int) -> discord.SelectOption:
        ok, reason = self.cog.m(item).health()
        return discord.SelectOption(label=f"Shard {item}", value=str(item), description=reason[:100],
                                    emoji=Status.OK if ok else Status.ERROR)

    def subtitle(self) -> str:
        healthy = sum(self.cog.m(i).health()[0] for i in self.items)
        return (f"{healthy} of {len(self.items)} healthy · average latency {self.cog.bot.latency * 1000:.0f} ms")

    def foot(self) -> str:
        return f"Alert threshold {self.cog.threshold} failed checks · sampled every 30 seconds"

    @property
    def accent(self) -> str:  # type: ignore[override]
        return "success" if all(self.cog.m(i).health()[0] for i in self.items) else "warning"

    def detail(self, item: int) -> discord.ui.Container[Any]:
        return self.cog.detail_card(item)

    async def _reload(self, interaction: discord.Interaction[Any]) -> None:
        self.replace_items(sorted(self.cog.metrics))
        await self.refresh(interaction)

    def list_controls(self) -> list[discord.ui.Item[Any]]:
        return [row(button("Refresh", self._reload))]

    def detail_controls(self, item: int) -> list[discord.ui.Item[Any]]:
        return [button("Refresh", self._reload)]


class ShardMonitor(commands.Cog, name="Shard Monitor"):
    """Latency, uptime, reconnects and event throughput per shard."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.metrics: dict[int, ShardMetrics] = {}
        self._tasks: list[asyncio.Task[Any]] = []

    def m(self, shard_id: int | None) -> ShardMetrics:
        sid = shard_id or 0
        if sid not in self.metrics:
            self.metrics[sid] = ShardMetrics(sid)
        return self.metrics[sid]

    @property
    def threshold(self) -> int:
        return self.bot.config.settings.shards.alert_threshold

    async def cog_load(self) -> None:
        for sid in self.bot.shards:
            self.m(sid)
        self._tasks = [asyncio.create_task(self._sample_loop())]

    async def cog_unload(self) -> None:
        for t in self._tasks:
            t.cancel()

    async def _sample_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            for sid, shard in self.bot.shards.items():
                metric = self.m(sid)
                if shard.latency == shard.latency and shard.latency != float("inf"):
                    metric.latencies.append(shard.latency * 1000)
                healthy, reason = metric.health()
                metric.failures = 0 if healthy else metric.failures + 1
                if metric.failures >= self.threshold and not metric.alerted:
                    metric.alerted = True
                    await self.bot.alerts.send("shards", f"Shard **{sid}** unhealthy: {reason}", "error")
                elif healthy and metric.alerted:
                    metric.alerted = False
                    await self.bot.alerts.send("shards", f"Shard **{sid}** recovered", "success")
            await asyncio.sleep(30)

    @commands.Cog.listener()
    async def on_shard_connect(self, shard_id: int) -> None:
        self.m(shard_id).connected()

    @commands.Cog.listener()
    async def on_shard_ready(self, shard_id: int) -> None:
        self.m(shard_id).event("ready")

    @commands.Cog.listener()
    async def on_shard_resumed(self, shard_id: int) -> None:
        metric = self.m(shard_id)
        metric.resumes += 1
        metric.connected()

    @commands.Cog.listener()
    async def on_shard_disconnect(self, shard_id: int) -> None:
        self.m(shard_id).disconnected()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild:
            metric = self.m(message.guild.shard_id)
            metric.messages += 1
            metric.event("message")

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context[Any]) -> None:
        if ctx.guild:
            self.m(ctx.guild.shard_id).commands += 1

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction[Any]) -> None:
        if interaction.guild:
            self.m(interaction.guild.shard_id).event("interaction")

    def guild_counts(self) -> Counter[int]:
        return Counter(g.shard_id for g in self.bot.guilds)

    def detail_card(self, shard_id: int) -> discord.ui.Container[Any]:
        metric = self.m(shard_id)
        ok, reason = metric.health()
        lat = list(metric.latencies)
        top = ", ".join(f"{k} {v:,}" for k, v in metric.events.most_common(5)) or "-"
        return cards.card(
            f"Shard {shard_id}",
            f"{Status.OK if ok else Status.ERROR} {reason}",
            cards.sep(),
            cards.kv({
                "Latency": f"{metric.latency_ms:.0f} ms (avg {metric.avg_ms:.0f}, min {min(lat, default=0):.0f}, "
                           f"max {max(lat, default=0):.0f})",
                "Trend": f"`{sparkline(lat[-40:])}`" if len(lat) > 1 else "-",
                "Uptime": f"{metric.uptime_pct:.3f}% · tracked {human_duration(time.time() - metric.started)}",
                "Connects / disconnects / resumes": f"{metric.connects} / {metric.disconnects} / {metric.resumes}",
                "Servers": self.guild_counts().get(shard_id, 0),
                "Messages / commands": f"{metric.messages:,} / {metric.commands:,}",
                "Top events": top,
                "Last event": cards.timestamp(metric.last_event),
            }),
            accent="success" if ok else "error",
        )

    @commands.hybrid_group(name="shard", description="Shard monitoring (bot owner)", invoke_without_command=True)
    @owner_only()
    async def shard(self, ctx: commands.Context[ZDBFBot]) -> None:
        await self.shard_monitor.callback(self, ctx)  # type: ignore[arg-type]

    @shard.command(name="monitor", description="Interactive shard dashboard")
    async def shard_monitor(self, ctx: commands.Context[ZDBFBot]) -> None:
        await MonitorView(self, ctx.author.id).send(ctx)

    @shard.command(name="details", description="Detailed metrics for one shard")
    async def shard_details(self, ctx: commands.Context[ZDBFBot], shard_id: int) -> None:
        if shard_id not in self.bot.shards:
            await ctx.send(view=cards.error("Unknown shard", f"This process runs shards {sorted(self.bot.shards)}."))
            return
        await ctx.send(view=cards.static(self.detail_card(shard_id)))

    @shard.command(name="health", description="Health report for all shards")
    async def shard_health(self, ctx: commands.Context[ZDBFBot]) -> None:
        lines = []
        for sid, metric in sorted(self.metrics.items()):
            ok, reason = metric.health()
            lines.append(f"{Status.OK if ok else Status.ERROR} **Shard {sid}** - {reason}"
                         + (f" · {metric.failures} failed checks" if metric.failures else ""))
        await Paginator.from_lines(lines or ["No shards tracked yet."], per_page=20, title="Shard health").send(ctx)

    @shard.command(name="alerts", description="Alert channel and failure threshold")
    async def shard_alerts(self, ctx: commands.Context[ZDBFBot], channel: discord.TextChannel | None = None,
                           threshold: app_commands.Range[int, 1, 20] | None = None) -> None:
        if channel is not None:
            await self.bot.alerts.set_channel("shards", channel.id)
        if threshold is not None:
            await self.bot.config.set("shards.alert_threshold", threshold)
        cid = self.bot.alerts.channel_for("shards")
        await ctx.send(view=cards.success("Shard alerts", cards.kv({
            "Channel": f"<#{cid}>" if cid else "*not set*", "Threshold": f"{self.threshold} failed checks"})))

    @shard.command(name="reset", description="Reset metrics for one shard (or all)")
    async def shard_reset(self, ctx: commands.Context[ZDBFBot], shard_id: int | None = None) -> None:
        targets = [shard_id] if shard_id is not None else list(self.metrics)
        for sid in targets:
            self.metrics[sid] = ShardMetrics(sid)
        await ctx.send(view=cards.success("Metrics reset", f"Shards: {', '.join(map(str, targets)) or 'none'}"))


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(ShardMonitor(bot))
