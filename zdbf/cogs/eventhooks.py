# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..core.hooks import BUILTIN_EVENTS
from ..core.permissions import owner_only
from ..ui import Paginator, Status, cards

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot


class EventHooks(commands.Cog, name="Event Hooks"):
    """Framework lifecycle events that extensions can subscribe to."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot

    async def _hook_ac(self, interaction: discord.Interaction[Any], current: str) -> list[app_commands.Choice[str]]:
        ids = [h.hook_id for h in self.bot.hooks.all_hooks()]
        return [app_commands.Choice(name=i[:100], value=i[:100]) for i in ids if current.lower() in i.lower()][:25]

    @commands.hybrid_group(name="eventhooks", description="Framework event hooks (bot owner)",
                           invoke_without_command=True)
    @owner_only()
    async def eventhooks(self, ctx: commands.Context[ZDBFBot]) -> None:
        await self.eh_list.callback(self, ctx)  # type: ignore[arg-type]

    @eventhooks.command(name="list", description="Registered hooks and their stats")
    async def eh_list(self, ctx: commands.Context[ZDBFBot]) -> None:
        bus = self.bot.hooks
        lines: list[str] = []
        events = sorted(set(BUILTIN_EVENTS) | set(bus.hooks))
        for event in events:
            hooks = bus.hooks.get(event, [])
            custom = "" if event in BUILTIN_EVENTS else " *(custom)*"
            lines.append(f"**{event}**{custom} · {len(hooks)} hook(s)")
            for h in hooks:
                if h.hook_id in bus.disabled:
                    state = f"{Status.OFF} disabled"
                elif bus.breaker.is_open(h.hook_id):
                    state = f"{Status.ERROR} circuit open"
                else:
                    state = Status.OK
                lines.append(f"-# {state} `{h.hook_id.split(':', 1)[1]}` · p{h.priority} · "
                             f"{h.executions} ok / {h.failures} failed · avg {h.avg_ms} ms")
        m = bus.metrics
        await Paginator.from_lines(
            lines, per_page=18, title="Event hooks",
            subtitle=f"emitted {m['emitted']} · executed {m['executed']} · failed {m['failed']} · "
                     f"dropped {m['dropped']} · worker {'running' if bus.running else 'STOPPED'}",
        ).send(ctx)

    @eventhooks.command(name="history", description="Recent hook executions")
    async def eh_history(self, ctx: commands.Context[ZDBFBot], event: str | None = None) -> None:
        items = [h for h in reversed(self.bot.hooks.history) if event is None or h.event == event]
        lines = []
        for h in items:
            icon = Status.OK if not h.failed else Status.WARN if h.succeeded else Status.ERROR
            lines.append(f"{icon} {cards.timestamp(h.timestamp)} **{h.event}** · {h.succeeded} ok / {h.failed} failed"
                         f" · avg {h.avg_ms} ms · queued {h.queue_delay_ms} ms")
            lines += [f"-# {cards.truncate(e, 200)}" for e in h.errors]
        await Paginator.from_lines(lines or ["*No hook executions yet.*"], per_page=15,
                                   title="Hook history").send(ctx)

    @eventhooks.command(name="disable", description="Disable a hook by id")
    @app_commands.autocomplete(hook_id=_hook_ac)
    async def eh_disable(self, ctx: commands.Context[ZDBFBot], *, hook_id: str) -> None:
        ok = self.bot.hooks.disable(self._resolve(hook_id))
        await ctx.send(view=(cards.success("Hook disabled", f"`{hook_id}`") if ok
                             else cards.error("Unknown hook", f"`{hook_id}`")))

    @eventhooks.command(name="enable", description="Re-enable a hook (also closes its circuit breaker)")
    @app_commands.autocomplete(hook_id=_hook_ac)
    async def eh_enable(self, ctx: commands.Context[ZDBFBot], *, hook_id: str) -> None:
        ok = self.bot.hooks.enable(self._resolve(hook_id))
        await ctx.send(view=(cards.success("Hook enabled", f"`{hook_id}`") if ok
                             else cards.warning("Nothing to do", "That hook was not disabled.")))

    @eventhooks.command(name="reset", description="Reset a hook's circuit breaker")
    @app_commands.autocomplete(hook_id=_hook_ac)
    async def eh_reset(self, ctx: commands.Context[ZDBFBot], *, hook_id: str) -> None:
        self.bot.hooks.breaker.reset(self._resolve(hook_id))
        await ctx.send(view=cards.success("Circuit breaker reset", f"`{hook_id}`"))

    @eventhooks.command(name="alerts", description="Set the channel for event-hook alerts")
    async def eh_alerts(self, ctx: commands.Context[ZDBFBot], channel: discord.TextChannel | None = None) -> None:
        await self.bot.alerts.set_channel("eventhooks", channel.id if channel else None)
        await ctx.send(view=cards.success("Event-hook alerts", f"→ {channel.mention if channel else '*cleared*'}"))

    def _resolve(self, hook_id: str) -> str:
        ids = [h.hook_id for h in self.bot.hooks.all_hooks()]
        if hook_id in ids:
            return hook_id
        matches = [i for i in ids if i.endswith(hook_id) or i.split(":", 1)[-1] == hook_id]
        return matches[0] if len(matches) == 1 else hook_id


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(EventHooks(bot))
