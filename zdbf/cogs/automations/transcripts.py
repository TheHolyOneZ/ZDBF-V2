# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import gzip
import io
import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord

from ...core.storage import write_bytes_durable
from ...ui import cards

if TYPE_CHECKING:
    from .cog import Automations
    from .engine import Automation

__all__ = ["ROOT", "TranscriptStore", "capture", "close_ticket", "render_text"]

ROOT = Path("data/tickets")
MESSAGE_LIMIT = 5000
KEEP_PER_GUILD = 500
_ID = re.compile(r"^\d{5,25}-\d{9,12}$")


async def capture(channel: discord.TextChannel, *, limit: int = MESSAGE_LIMIT) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    async for m in channel.history(limit=limit, oldest_first=True):
        out.append({
            "id": str(m.id), "at": m.created_at.timestamp(),
            "author": {"id": str(m.author.id), "name": m.author.display_name, "bot": m.author.bot},
            "content": m.content,
            "attachments": [{"name": a.filename, "url": a.url, "size": a.size} for a in m.attachments],
            "embeds": [e.title or e.description or "" for e in m.embeds][:5],
            "edited": m.edited_at.timestamp() if m.edited_at else None,
        })
    return out


def render_text(record: dict[str, Any]) -> str:
    def when(ts: float | None) -> str:
        return dt.datetime.fromtimestamp(ts or 0, dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        f"Ticket #{record['channel_name']} in {record['guild_name']}",
        f"Opened by {record['owner'].get('name') or record['owner'].get('id') or 'unknown'} on {when(record['opened_at'])}",
        f"Closed by {record['closed_by']} on {when(record['closed_at'])}",
        f"{len(record['messages'])} messages", "",
    ]
    for m in record["messages"]:
        lines.append(f"[{when(m['at'])}] {m['author']['name']}{' (bot)' if m['author']['bot'] else ''}:")
        if m["content"]:
            lines.extend(f"  {line}" for line in m["content"].splitlines())
        for e in m["embeds"]:
            if e:
                lines.append(f"  [card] {e[:300]}")
        for a in m["attachments"]:
            lines.append(f"  [file] {a['name']} {a['url']}")
    return "\n".join(lines) + "\n"


class TranscriptStore:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        self._lock = asyncio.Lock()

    def _dir(self, guild_id: int) -> Path:
        return self.root / str(int(guild_id))

    def _index(self, guild_id: int) -> list[dict[str, Any]]:
        try:
            data = json.loads((self._dir(guild_id) / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    async def save(self, record: dict[str, Any]) -> dict[str, Any]:
        guild_id = int(record["guild_id"])
        tid = f"{record['channel_id']}-{int(record['closed_at'])}"
        record["id"] = tid
        summary = {k: record[k] for k in ("id", "guild_id", "channel_id", "channel_name", "owner", "opened_at",
                                          "closed_at", "closed_by", "automation")}
        summary["messages"] = len(record["messages"])

        def write() -> None:
            folder = self._dir(guild_id)
            folder.mkdir(parents=True, exist_ok=True)
            write_bytes_durable(folder / f"{tid}.json.gz", gzip.compress(json.dumps(record).encode(), 6))
            index = [summary, *[e for e in self._index(guild_id) if e.get("id") != tid]]
            for old in index[KEEP_PER_GUILD:]:
                (folder / f"{old['id']}.json.gz").unlink(missing_ok=True)
            write_bytes_durable(folder / "index.json", json.dumps(index[:KEEP_PER_GUILD]).encode())

        async with self._lock:
            await asyncio.to_thread(write)
        return summary

    async def list(self, guild_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._index, guild_id)

    async def load(self, guild_id: int, tid: str) -> dict[str, Any] | None:
        if not _ID.match(tid):
            return None
        path = self._dir(guild_id) / f"{tid}.json.gz"

        def read() -> dict[str, Any] | None:
            try:
                return json.loads(gzip.decompress(path.read_bytes()))
            except (OSError, ValueError):
                return None

        return await asyncio.to_thread(read)

    async def delete(self, guild_id: int, tid: str) -> bool:
        if not _ID.match(tid):
            return False

        def remove() -> bool:
            folder = self._dir(guild_id)
            index = self._index(guild_id)
            kept = [e for e in index if e.get("id") != tid]
            (folder / f"{tid}.json.gz").unlink(missing_ok=True)
            if len(kept) == len(index):
                return False
            write_bytes_durable(folder / "index.json", json.dumps(kept).encode())
            return True

        async with self._lock:
            return await asyncio.to_thread(remove)


async def close_ticket(cog: Automations, auto: Automation, channel: discord.TextChannel, closed_by: str, *,
                       delay: float = 5.0) -> dict[str, Any] | None:
    owner_id = await cog.runtime.state_get(auto, channel.id, "ticket_owner")
    summary = None
    if auto.config.get("transcripts", True):
        owner = channel.guild.get_member(int(owner_id)) if owner_id else None
        record = {
            "guild_id": str(channel.guild.id), "guild_name": channel.guild.name, "channel_id": str(channel.id),
            "channel_name": channel.name, "automation": auto.hook_id, "opened_at": channel.created_at.timestamp(),
            "closed_at": time.time(), "closed_by": closed_by,
            "owner": {"id": str(owner_id) if owner_id else None, "name": owner.display_name if owner else None},
            "messages": await capture(channel),
        }
        summary = await cog.transcripts.save(record)
        target = cog.runtime.channel(auto.config.get("transcript_channel_id"))
        if isinstance(target, discord.TextChannel):
            name = f"{re.sub(r'[^A-Za-z0-9_-]', '_', channel.name)}-transcript.txt"
            file = discord.File(io.BytesIO(render_text(record).encode()), filename=name)
            box = cards.card(
                f"Ticket #{channel.name} closed",
                (f"Opened by <@{owner_id}> · " if owner_id else "")
                + f"closed by {discord.utils.escape_markdown(closed_by)} · {len(record['messages'])} messages",
                accent="muted")
            box.add_item(discord.ui.File(f"attachment://{name}"))
            with contextlib.suppress(discord.HTTPException):
                await target.send(view=cards.static(box), files=[file], allowed_mentions=discord.AllowedMentions.none())
    if owner_id:
        await cog.runtime.state_delete(auto, int(owner_id), "open_ticket")
    await cog.runtime.state_delete(auto, channel.id, "ticket_owner")
    await asyncio.sleep(delay)
    with contextlib.suppress(discord.HTTPException):
        await channel.delete(reason=f"Ticket closed by {closed_by}")
    return summary
