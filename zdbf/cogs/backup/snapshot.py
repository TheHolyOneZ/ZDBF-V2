# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import base64
import contextlib
import gzip
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord

from ...core.database import Database, utcnow_iso
from ...core.storage import write_bytes_durable

if TYPE_CHECKING:
    from ...core.bot import ZDBFBot

log = logging.getLogger("zdbf.backup")

SNAPSHOT_VERSION = "3.0"
COMPONENTS: dict[str, tuple[str, str]] = {
    "roles": ("", "Roles"),
    "categories": ("", "Categories"),
    "channels": ("", "Channels"),
    "emojis": ("", "Emojis"),
    "stickers": ("", "Stickers"),
    "server_settings": ("", "Server settings"),
    "server_images": ("", "Icon & banner"),
    "member_roles": ("", "Member roles"),
    "bot_settings": ("", "Bot settings"),
}
CHANNEL_KINDS = ("text_channels", "voice_channels", "forum_channels", "stage_channels")


def checksum(data: dict[str, Any]) -> str:
    raw = json.dumps({k: v for k, v in data.items() if k != "meta"}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def counts(snap: dict[str, Any]) -> dict[str, int]:
    return {
        "roles": len(snap.get("roles", [])),
        "categories": len(snap.get("categories", [])),
        "channels": sum(len(snap.get(k, [])) for k in CHANNEL_KINDS),
        "emojis": len(snap.get("emojis", [])),
        "stickers": len(snap.get("stickers", [])),
        "members": len(snap.get("member_roles", [])),
    }


def _overwrites(channel: discord.abc.GuildChannel) -> list[dict[str, Any]]:
    out = []
    for target, ow in channel.overwrites.items():
        allow, deny = ow.pair()
        out.append({"target_id": target.id, "target_name": getattr(target, "name", None),
                    "target_type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value, "deny": deny.value})
    return out


async def _b64(asset: discord.Asset | discord.Emoji | discord.GuildSticker | None) -> str | None:
    if asset is None:
        return None
    with contextlib.suppress(discord.HTTPException, discord.NotFound, ValueError):
        return base64.b64encode(await asset.read()).decode()
    return None


async def capture(guild: discord.Guild, bot: ZDBFBot, components: set[str] | None = None) -> dict[str, Any]:
    comps = set(components or COMPONENTS)
    snap: dict[str, Any] = {
        "version": SNAPSHOT_VERSION,
        "captured_at": utcnow_iso(),
        "components": sorted(comps),
        "guild": {
            "id": guild.id, "name": guild.name, "owner_id": guild.owner_id, "member_count": guild.member_count,
            "created_at": guild.created_at.isoformat(), "premium_tier": guild.premium_tier,
            "icon_url": guild.icon.url if guild.icon else None, "banner_url": guild.banner.url if guild.banner else None,
        },
    }
    if "server_images" in comps:
        snap["guild"]["icon_b64"] = await _b64(guild.icon)
        snap["guild"]["banner_b64"] = await _b64(guild.banner)
    if "server_settings" in comps:
        snap["server_settings"] = {
            "verification_level": guild.verification_level.value,
            "default_notifications": guild.default_notifications.value,
            "explicit_content_filter": guild.explicit_content_filter.value,
            "afk_timeout": guild.afk_timeout,
            "afk_channel": guild.afk_channel.name if guild.afk_channel else None,
            "system_channel": guild.system_channel.name if guild.system_channel else None,
            "rules_channel": guild.rules_channel.name if guild.rules_channel else None,
            "public_updates_channel": guild.public_updates_channel.name if guild.public_updates_channel else None,
            "preferred_locale": str(guild.preferred_locale),
            "premium_progress_bar_enabled": guild.premium_progress_bar_enabled,
            "description": guild.description,
        }
    if "roles" in comps:
        snap["roles"] = [
            {"id": r.id, "name": r.name, "color": r.colour.value, "hoist": r.hoist, "mentionable": r.mentionable,
             "permissions_value": r.permissions.value, "position": r.position,
             "icon_b64": await _b64(r.icon) if r.icon else None, "unicode_emoji": r.unicode_emoji}
            for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
            if not r.is_default() and not r.managed
        ]
        snap["default_role_permissions"] = guild.default_role.permissions.value
    if "categories" in comps:
        snap["categories"] = [{"id": c.id, "name": c.name, "position": c.position, "nsfw": c.nsfw,
                               "overwrites": _overwrites(c)} for c in guild.categories]
    if "channels" in comps:
        snap["text_channels"] = [
            {"id": c.id, "name": c.name, "topic": c.topic, "slowmode_delay": c.slowmode_delay, "nsfw": c.nsfw,
             "news": c.is_news(), "position": c.position, "category_id": c.category_id,
             "default_auto_archive_duration": c.default_auto_archive_duration, "overwrites": _overwrites(c)}
            for c in guild.text_channels
        ]
        snap["voice_channels"] = [
            {"id": c.id, "name": c.name, "bitrate": c.bitrate, "user_limit": c.user_limit, "position": c.position,
             "category_id": c.category_id, "rtc_region": c.rtc_region, "nsfw": c.nsfw, "overwrites": _overwrites(c)}
            for c in guild.voice_channels
        ]
        snap["forum_channels"] = [
            {"id": c.id, "name": c.name, "topic": c.topic, "nsfw": c.nsfw, "slowmode_delay": c.slowmode_delay,
             "position": c.position, "category_id": c.category_id, "overwrites": _overwrites(c),
             "tags": [{"name": t.name, "emoji": str(t.emoji) if t.emoji else None, "moderated": t.moderated}
                      for t in c.available_tags]}
            for c in guild.forums
        ]
        snap["stage_channels"] = [
            {"id": c.id, "name": c.name, "topic": c.topic, "position": c.position, "category_id": c.category_id,
             "overwrites": _overwrites(c)}
            for c in guild.stage_channels
        ]
    if "emojis" in comps:
        snap["emojis"] = [{"id": e.id, "name": e.name, "animated": e.animated, "url": str(e.url),
                           "image_b64": await _b64(e)} for e in guild.emojis if not e.managed]
    if "stickers" in comps:
        snap["stickers"] = [{"id": s.id, "name": s.name, "description": s.description, "emoji": s.emoji,
                             "format": s.format.name, "image_b64": await _b64(s)} for s in guild.stickers]
    if "member_roles" in comps:
        if not guild.chunked:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(guild.chunk(cache=True), timeout=60)
        trackable = {r.id: r.name for r in guild.roles if not r.is_default() and not r.managed}
        snap["member_roles"] = [
            {"user_id": m.id, "username": str(m), "role_ids": [r.id for r in m.roles if r.id in trackable],
             "role_names": [r.name for r in m.roles if r.id in trackable]}
            for m in guild.members if not m.bot and any(r.id in trackable for r in m.roles)
        ]
    if "bot_settings" in comps:
        perms = await bot.db.list_command_permissions(guild.id)
        role_names = {r.id: r.name for r in guild.roles}
        snap["bot_settings"] = {
            "custom_prefix": await bot.db.get_guild_prefix(guild.id),
            "mention_prefix_enabled": await bot.db.get_guild_mention_prefix_enabled(guild.id),
            "command_permissions": {cmd: [role_names.get(r, str(r)) for r in roles] for cmd, roles in perms.items()},
        }
    return snap


@dataclass
class BackupEntry:
    backup_id: str
    guild_id: int
    label: str
    note: str | None
    pinned: bool
    automatic: bool
    created_by: int
    created_at: str
    size_bytes: int
    checksum: str
    version: str
    components: list[str]
    counts: dict[str, int]
    file: str

    @classmethod
    def from_row(cls, r: Any) -> BackupEntry:
        return cls(r["backup_id"], r["guild_id"], r["label"], r["note"], bool(r["pinned"]), bool(r["automatic"]),
                   r["created_by"], r["created_at"], r["size_bytes"], r["checksum"], r["version"],
                   json.loads(r["components"]), json.loads(r["counts"]), r["file"])


class BackupStorage:
    def __init__(self, db: Database, root: str | Path = "data/backups") -> None:
        self.db = db
        self.root = Path(root)

    def _path(self, guild_id: int, backup_id: str) -> Path:
        return self.root / str(guild_id) / f"{backup_id}.json.gz"

    async def save(self, guild_id: int, snap: dict[str, Any], *, label: str, user_id: int,
                   automatic: bool = False) -> BackupEntry:
        backup_id = secrets.token_hex(6)
        digest = checksum(snap)
        snap["meta"] = {"backup_id": backup_id, "checksum": digest}
        raw = json.dumps(snap, default=str, separators=(",", ":")).encode()
        path = self._path(guild_id, backup_id)

        def write() -> int:
            write_bytes_durable(path, gzip.compress(raw, compresslevel=6))
            return path.stat().st_size

        size = await asyncio.to_thread(write)
        entry = BackupEntry(backup_id, guild_id, label[:100], None, False, automatic, user_id, utcnow_iso(), size,
                            digest, snap.get("version", SNAPSHOT_VERSION), snap.get("components", []), counts(snap),
                            str(path))
        try:
            async with self.db.transaction():
                await self.db.execute(
                    "INSERT INTO backups (backup_id, guild_id, label, note, pinned, automatic, created_by, created_at, "
                    "size_bytes, checksum, version, components, counts, file) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (entry.backup_id, guild_id, entry.label, None, 0, int(automatic), user_id, entry.created_at, size,
                     digest, entry.version, json.dumps(entry.components), json.dumps(entry.counts), entry.file))
                await self.audit(guild_id, "create", user_id, backup_id, label)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return entry

    async def load(self, entry: BackupEntry) -> dict[str, Any] | None:
        def read() -> dict[str, Any] | None:
            path = Path(entry.file)
            if not path.exists():
                return None
            data = path.read_bytes()
            if path.suffix == ".gz":
                data = gzip.decompress(data)
            return json.loads(data)

        try:
            return await asyncio.to_thread(read)
        except (OSError, ValueError, EOFError) as exc:
            log.error("cannot read backup %s: %s", entry.backup_id, exc)
            return None

    async def list(self, guild_id: int) -> list[BackupEntry]:
        rows = await self.db.fetchall("SELECT * FROM backups WHERE guild_id = ? ORDER BY created_at DESC", (guild_id,))
        return [BackupEntry.from_row(r) for r in rows]

    async def get(self, guild_id: int, backup_id: str) -> BackupEntry | None:
        row = await self.db.fetchone("SELECT * FROM backups WHERE guild_id = ? AND backup_id = ?", (guild_id, backup_id))
        return BackupEntry.from_row(row) if row else None

    async def delete(self, entry: BackupEntry, user_id: int) -> None:
        async with self.db.transaction():
            await self.db.execute("DELETE FROM backups WHERE backup_id = ?", (entry.backup_id,))
            await self.audit(entry.guild_id, "delete", user_id, entry.backup_id, entry.label)
        Path(entry.file).unlink(missing_ok=True)

    async def update(self, entry: BackupEntry, **fields: Any) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        await self.db.execute(f"UPDATE backups SET {cols} WHERE backup_id = ?", (*fields.values(), entry.backup_id))

    async def verify(self, entry: BackupEntry) -> tuple[bool, str]:
        snap = await self.load(entry)
        if snap is None:
            return False, "file missing or unreadable"
        actual = checksum(snap)
        if actual != entry.checksum:
            return False, f"checksum mismatch (expected {entry.checksum}, got {actual})"
        return True, "checksum OK"

    async def audit(self, guild_id: int, action: str, user_id: int, backup_id: str | None = None,
                    details: str = "") -> None:
        await self.db.execute(
            "INSERT INTO backup_audit (guild_id, action, user_id, backup_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, action, user_id, backup_id, details[:500], utcnow_iso()))

    async def audit_log(self, guild_id: int, limit: int = 50) -> list[Any]:
        return await self.db.fetchall(
            "SELECT * FROM backup_audit WHERE guild_id = ? ORDER BY id DESC LIMIT ?", (guild_id, limit))

    async def enforce_limits(self, guild_id: int, max_count: int, retention_days: int) -> int:
        import datetime as dt

        removed = 0
        entries = await self.list(guild_id)
        unpinned = [e for e in entries if not e.pinned]
        for e in unpinned[max(0, max_count - (len(entries) - len(unpinned))):]:
            await self.delete(e, 0)
            removed += 1
        if retention_days > 0:
            cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=retention_days)
            for e in await self.list(guild_id):
                if not e.pinned and dt.datetime.fromisoformat(e.created_at) < cutoff:
                    await self.delete(e, 0)
                    removed += 1
        return removed


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    prefix = {"text_channels": "#", "voice_channels": "voice: ", "forum_channels": "forum: ", "stage_channels": "stage: "}

    def names(snap: dict[str, Any], keys: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        return {f"{prefix.get(k, '')}{item['name']}": item for k in keys for item in snap.get(k, [])}

    out: dict[str, dict[str, list[str]]] = {}
    for label, keys, fields in (
        ("roles", ("roles",), ("color", "permissions_value", "hoist", "mentionable")),
        ("categories", ("categories",), ()),
        ("channels", CHANNEL_KINDS, ("topic", "nsfw", "slowmode_delay", "category_id")),
        ("emojis", ("emojis",), ()),
        ("stickers", ("stickers",), ()),
    ):
        a, b = names(old, keys), names(new, keys)
        changed = [n for n in a.keys() & b.keys() if any(a[n].get(f) != b[n].get(f) for f in fields)
                   and not (label == "channels" and _same_category(a[n], b[n], old, new))]
        out[label] = {"added": sorted(b.keys() - a.keys()), "removed": sorted(a.keys() - b.keys()),
                      "changed": sorted(changed)}
    return out


def _same_category(a: dict[str, Any], b: dict[str, Any], old: dict[str, Any], new: dict[str, Any]) -> bool:
    other_fields_equal = all(a.get(f) == b.get(f) for f in ("topic", "nsfw", "slowmode_delay"))
    cat = lambda snap, cid: next((c["name"] for c in snap.get("categories", []) if c["id"] == cid), None)  # noqa: E731
    return other_fields_equal and cat(old, a.get("category_id")) == cat(new, b.get("category_id"))
