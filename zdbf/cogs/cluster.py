# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from discord.ext import commands

from ..core.ipc import Frame, IPCClient, IPCError, IPCServer
from ..core.permissions import owner_only
from ..ui import Paginator, Status, cards, chunk_lines
from ..utils import human_duration

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot

log = logging.getLogger("zdbf.cluster")


class Cluster(commands.Cog, name="Cluster"):
    """Cross-process communication between shard clusters."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        cfg = bot.config.settings.cluster
        self.mode = os.getenv("SHARD_IPC_MODE", cfg.mode).lower()
        self.name = os.getenv("SHARD_CLUSTER_NAME", cfg.name)
        self.host = os.getenv("SHARD_IPC_HOST", cfg.host)
        self.port = int(os.getenv("SHARD_IPC_PORT", cfg.port))
        self.peer: IPCServer | IPCClient

    def info(self) -> dict[str, Any]:
        return {"shard_ids": sorted(self.bot.shards), "shard_count": self.bot.shard_count,
                "guild_count": len(self.bot.guilds), "latency_ms": round(self.bot.latency * 1000, 1),
                "uptime": round(self.bot.metrics.uptime)}

    async def cog_load(self) -> None:
        secret = self.bot.config.secrets.ipc_secret
        if len(secret) < 16 or secret == "change_me_please":
            raise IPCError("set SHARD_IPC_SECRET (16+ random characters) in .env to use the cluster module")
        if self.mode == "server":
            self.peer = IPCServer(self.host, self.port, secret, self.name)
            await self.peer.start()
        else:
            self.peer = IPCClient(self.host, self.port, secret, self.name, info=self.info)
            self.peer.start()
        self.peer.on("stats", self._on_stats)
        self.peer.on("broadcast", self._on_broadcast)

    async def cog_unload(self) -> None:
        await self.peer.stop()

    async def _on_stats(self, frame: Frame) -> None:
        await self.peer.reply(frame, "stats_reply", {"cluster": self.name, **self.info()})

    async def _on_broadcast(self, frame: Frame) -> None:
        log.info("broadcast from %s: %s", frame.source, frame.data.get("message"))
        await self.bot.hooks.emit("cluster_broadcast", source=frame.source, message=frame.data.get("message"),
                                  data=frame.data)

    async def gather_stats(self) -> list[dict[str, Any]]:
        mine = [{"cluster": self.name, **self.info(), "self": True}]
        try:
            replies = await self.peer.request("stats", timeout=2.5)
        except IPCError:
            replies = []
        return mine + [r.data for r in replies]

    @commands.hybrid_group(name="cluster", description="Shard clusters (bot owner)", invoke_without_command=True)
    @owner_only()
    async def cluster(self, ctx: commands.Context[ZDBFBot]) -> None:
        await self.cluster_status.callback(self, ctx)  # type: ignore[arg-type]

    @cluster.command(name="status", description="All connected clusters")
    async def cluster_status(self, ctx: commands.Context[ZDBFBot]) -> None:
        await ctx.defer()
        stats = await self.gather_stats()
        lines = [f"{Status.OK} **{s['cluster']}**{' *(this process)*' if s.get('self') else ''} · shards {s.get('shard_ids')} · "
                 f"{s.get('guild_count', 0):,} servers · {s.get('latency_ms', 0):.0f} ms · up {human_duration(s.get('uptime', 0))}"
                 for s in stats]
        total = sum(s.get("guild_count", 0) for s in stats)
        await Paginator.from_lines(
            lines, per_page=12, title="Clusters",
            subtitle=f"{len(stats)} clusters · {total:,} servers · mode {self.mode} · this cluster: {self.name}",
        ).send(ctx)

    @cluster.command(name="ipc", description="IPC connection diagnostics")
    async def cluster_ipc(self, ctx: commands.Context[ZDBFBot]) -> None:
        p = self.peer
        details: dict[str, Any] = {"Mode": self.mode, "Name": self.name, "Address": f"{self.host}:{self.port}",
                                   "Frames sent / received / rejected":
                                       f"{p.stats['sent']} / {p.stats['received']} / {p.stats['rejected']}"}
        extra = ""
        if isinstance(p, IPCServer):
            details["Listening"] = p.running
            extra = "\n".join(f"{Status.OK} **{n}**  {i['address']} · heartbeat "
                              f"{human_duration(time.time() - i['last_heartbeat'])} ago" for n, i in p.client_info.items())
        else:
            details.update({"Connected": p.connected, "Server": p.server_name or "-", "Reconnects": p.reconnects,
                            "Last error": p.last_error or "-"})
        pages = [[cards.kv(details)] + ([cards.sep(), "**Connected clients**\n" + chunk] if extra else [])
                 for chunk in (chunk_lines(extra.splitlines(), per_page=15) if extra else [""])]
        await Paginator(pages, title="IPC connection").send(ctx)

    @cluster.command(name="broadcast", description="Send a message to every cluster (emits 'cluster_broadcast')")
    async def cluster_broadcast(self, ctx: commands.Context[ZDBFBot], *, message: str) -> None:
        try:
            await self.peer.send(Frame("broadcast", {"message": message[:1500]}, source=self.name))
        except IPCError as exc:
            await ctx.send(view=cards.error("Broadcast failed", str(exc)))
            return
        await ctx.send(view=cards.success("Broadcast sent", cards.truncate(message, 500)))


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(Cluster(bot))
