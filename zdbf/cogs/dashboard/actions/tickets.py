# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import json
from typing import Any

import discord

from ....cogs.automations.transcripts import close_ticket, render_text
from . import ActionContext, ActionError, action
from .servers import guild_of

_closing: set[asyncio.Task[Any]] = set()


def _cog(ctx: ActionContext) -> Any:
    cog = ctx.bot.get_cog("Automations")
    if cog is None:
        raise ActionError("The automations module is switched off on the bot ([modules] automations).")
    return cog


@action("tickets.list", "view", timeout=30)
async def listing(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    autos = {a.hook_id: a for a in cog.for_guild(guild.id) if a.template == "tickets"}
    open_tickets = []
    if autos:
        marks = ",".join("?" * len(autos))
        rows = await ctx.bot.db.fetchall(
            f"SELECT hook_id, scope_id, value FROM automation_state WHERE key = 'ticket_owner' AND hook_id IN ({marks})",
            tuple(autos))
        for r in rows:
            channel = guild.get_channel(int(r["scope_id"]))
            if not isinstance(channel, discord.TextChannel):
                continue
            owner_id = json.loads(r["value"])
            owner = guild.get_member(int(owner_id)) if owner_id else None
            last = channel.last_message_id
            open_tickets.append({
                "channel_id": str(channel.id), "name": channel.name, "automation": r["hook_id"],
                "automation_name": autos[r["hook_id"]].name, "opened_at": channel.created_at.timestamp(),
                "owner": {"id": str(owner_id), "name": owner.display_name if owner else None},
                "last_activity": discord.utils.snowflake_time(last).timestamp() if last else None,
            })
    open_tickets.sort(key=lambda t: t["opened_at"], reverse=True)
    return {"open": open_tickets, "transcripts": await cog.transcripts.list(guild.id),
            "automations": [{"id": a.hook_id, "name": a.name, "transcripts": a.config.get("transcripts", True)}
                            for a in autos.values()]}


@action("tickets.transcript", "chat.read", timeout=30)
async def transcript(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    record = await cog.transcripts.load(guild.id, ctx.text("id", max_length=40))
    if record is None:
        raise ActionError("That transcript does not exist.")
    return {"transcript": record, "text": render_text(record)}


@action("tickets.close", "automations", timeout=30, summary=lambda a: f"close ticket channel {a.get('channel_id')}")
async def close(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    channel = guild.get_channel(ctx.integer("channel_id", minimum=1))
    if not isinstance(channel, discord.TextChannel):
        raise ActionError("That ticket channel no longer exists.")
    autos = [a for a in cog.for_guild(guild.id) if a.template == "tickets"]
    for auto in autos:
        if await cog.runtime.state_get(auto, channel.id, "ticket_owner") is not None:
            break
    else:
        raise ActionError("That channel is not an open ticket.")
    name = f"{ctx.user.get('name') or 'someone'} (dashboard)"
    try:
        await channel.send(f"This ticket is being closed from the dashboard by {discord.utils.escape_markdown(name)}.",
                           allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass
    task = asyncio.get_running_loop().create_task(close_ticket(cog, auto, channel, name, delay=3))
    _closing.add(task)
    task.add_done_callback(_closing.discard)
    return {"closing": str(channel.id)}


@action("tickets.delete", "automations", timeout=20, summary=lambda a: f"delete ticket transcript {a.get('id')}")
async def delete(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    if not await cog.transcripts.delete(guild.id, ctx.text("id", max_length=40)):
        raise ActionError("That transcript does not exist.")
    return {"deleted": True}
