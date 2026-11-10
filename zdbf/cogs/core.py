# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import os
import platform
import time
from typing import TYPE_CHECKING, Any, Literal

import discord
import psutil
from discord import app_commands
from discord.ext import commands

from .. import __version__
from ..ui import Glyph, Paginator, Status, cards, link_button, row
from ..utils import human_bytes, human_duration, plural
from .help import (
    FEATURES,
    MARKETPLACE_URL,
    NEW_IN_V2,
    credits_button,
    link_buttons,
    open_help,
    send_group_help,
)

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot

__all__ = ["Core", "send_group_help"]


class Core(commands.Cog, name="General"):
    """Help, framework info, latency and statistics."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.process = psutil.Process(os.getpid())

    async def _command_autocomplete(self, interaction: discord.Interaction[Any],
                                    current: str) -> list[app_commands.Choice[str]]:
        current = current.lower()
        names = sorted({c.qualified_name for c in self.bot.walk_commands() if not c.hidden})
        return [app_commands.Choice(name=n, value=n) for n in names if current in n][:25]

    @commands.hybrid_command(name="help", description="Browse every command, or get details on one")
    @app_commands.describe(command="A command to show details for")
    @app_commands.autocomplete(command=_command_autocomplete)
    async def help_command(self, ctx: commands.Context[ZDBFBot], *, command: str | None = None) -> None:
        await open_help(ctx, command)

    @commands.hybrid_command(
        name="about",
        aliases=["discordbotframework", "framework", "botinfo"],
        description="Framework information, features and credits",
    )
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def about(self, ctx: commands.Context[ZDBFBot]) -> None:
        bot = self.bot
        stats = {
            "Uptime": human_duration(bot.metrics.uptime),
            "Servers": f"{len(bot.guilds):,}",
            "Extensions": f"{len(bot.extensions)}",
            "Latency": f"{bot.latency * 1000:.0f} ms",
            "Shards": bot.shard_count or 1,
        }
        box = cards.card(
            "Zoryx Discord Bot Framework",
            "A modular, production-grade framework for discord.py.",
            cards.sep(),
            "**Capabilities**\n" + "\n".join(f"{Glyph.BULLET} {f}" for f in FEATURES),
            cards.sep(),
            "**New in V2**\n" + "\n".join(f"{Glyph.BULLET} {f}" for f in NEW_IN_V2),
            cards.sep(),
            "**Runtime**\n" + cards.kv(stats, code=True),
            subtitle=f"Version {__version__}",
            accent="brand",
            thumbnail=bot.user.display_avatar.url if bot.user else None,
            foot=f"Created by TheHolyOneZ · Requested by {ctx.author}",
        )
        box.add_item(row(credits_button(), *link_buttons(bot),
                         link_button("ZSync Marketplace", MARKETPLACE_URL)))
        await ctx.send(view=cards.static(box))

    @commands.hybrid_command(name="ping", description="Gateway, API and database latency")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def ping(self, ctx: commands.Context[ZDBFBot]) -> None:
        start = time.perf_counter()
        await ctx.defer()
        api_ms = (time.perf_counter() - start) * 1000
        db_start = time.perf_counter()
        await self.bot.db.fetchval("SELECT 1")
        db_ms = (time.perf_counter() - db_start) * 1000
        ws_ms = self.bot.latency * 1000

        def mark(ms: float) -> str:
            return Status.OK if ms < 150 else Status.WARN if ms < 400 else Status.ERROR

        await ctx.send(view=cards.static(cards.card(
            "Latency",
            "\n".join([
                f"{mark(ws_ms)} **Gateway**  `{ws_ms:.0f} ms`",
                f"{mark(api_ms)} **API round-trip**  `{api_ms:.0f} ms`",
                f"{mark(db_ms * 10)} **Database**  `{db_ms:.2f} ms`",
            ]),
            accent="success" if ws_ms < 200 else "warning",
        )))

    @commands.hybrid_group(name="stats", fallback="overview", description="Bot statistics",
                           invoke_without_command=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def stats(self, ctx: commands.Context[ZDBFBot]) -> None:
        bot = self.bot
        with self.process.oneshot():
            mem = self.process.memory_info().rss
            cpu = self.process.cpu_percent(interval=None)
            threads = self.process.num_threads()
        users = sum(g.member_count or 0 for g in bot.guilds)
        m = bot.metrics
        top = "\n".join(f"`{n}`  {c:,}" for n, c in m.command_counter.most_common(5)) or "*None yet.*"
        box = cards.card(
            "Statistics",
            cards.kv({
                "Uptime": human_duration(m.uptime),
                "Servers": f"{len(bot.guilds):,}",
                "Members": f"{users:,}",
                "Shards": bot.shard_count or 1,
                "Latency": f"{bot.latency * 1000:.0f} ms",
            }),
            cards.sep(),
            cards.kv({
                "Commands run": f"{m.commands_total:,}",
                "Errors": f"{m.errors_total:,} ({m.error_rate():.1f}% last hour)",
                "Messages seen": f"{m.messages_seen:,}",
                "Interactions": f"{m.interactions_total:,}",
                "Extensions": len(bot.extensions),
                "Cogs": len(bot.cogs),
            }),
            cards.sep(),
            cards.kv({
                "Memory": human_bytes(mem),
                "CPU": f"{cpu:.1f}%",
                "Threads": threads,
                "Python": platform.python_version(),
                "discord.py": discord.__version__,
                "ZDBF": __version__,
            }),
            cards.sep(),
            "**Most used this session**\n" + top,
            accent="primary",
            foot="Updated " + cards.timestamp(),
        )
        await ctx.send(view=cards.static(box))

    @stats.command(name="shards", description="Per-shard latency and server counts")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def stats_shards(self, ctx: commands.Context[ZDBFBot]) -> None:
        bot = self.bot
        current = ctx.guild.shard_id if ctx.guild else 0
        counts: dict[int, int] = {}
        for g in bot.guilds:
            counts[g.shard_id] = counts.get(g.shard_id, 0) + 1
        lines = []
        for sid, shard in sorted(bot.shards.items()):
            lat = shard.latency * 1000 if shard.latency == shard.latency else -1
            state = Status.ERROR if shard.is_closed() else Status.OK if lat < 400 else Status.WARN
            here = "  *(this server)*" if sid == current else ""
            lines.append(f"{state} **Shard {sid}**  `{lat:.0f} ms` · {plural(counts.get(sid, 0), 'server')}{here}")
        await Paginator.from_lines(
            lines or ["Not sharded."], per_page=15, title="Shards",
            subtitle=f"{bot.shard_count or 1} total · average {bot.latency * 1000:.0f} ms",
        ).send(ctx)

    @stats.command(name="commands", description="Most used commands (all time)")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def stats_commands(self, ctx: commands.Context[ZDBFBot],
                             scope: Literal["server", "global"] = "server") -> None:
        guild_id = ctx.guild.id if ctx.guild and scope != "global" else None
        rows = await self.bot.db.get_command_stats(guild_id, limit=50)
        lines = [f"`{i:>2}.` **{name}**  {count:,}" for i, (name, count) in enumerate(rows, 1)]
        await Paginator.from_lines(
            lines or ["*No usage recorded yet.*"], per_page=15,
            title="Command usage",
            subtitle="this server" if guild_id else "all servers",
        ).send(ctx)


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(Core(bot))
