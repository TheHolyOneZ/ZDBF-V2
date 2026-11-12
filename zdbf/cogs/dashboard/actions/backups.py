# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import re
from typing import Any

from ....cogs.backup.restore import Restorer, RestoreReport
from ....cogs.backup.snapshot import COMPONENTS, BackupEntry, capture, diff
from . import ActionContext, ActionError, action
from .servers import guild_of

_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _cog(ctx: ActionContext) -> Any:
    cog = ctx.bot.get_cog("Backup")
    if cog is None:
        raise ActionError("The backup module is switched off on the bot ([modules] backup).")
    return cog


def _entry(entry: BackupEntry) -> dict[str, Any]:
    return {"id": entry.backup_id, "label": entry.label, "note": entry.note, "pinned": entry.pinned,
            "automatic": entry.automatic, "created_by": str(entry.created_by), "created_at": entry.created_at,
            "size": entry.size_bytes, "components": entry.components, "counts": entry.counts, "version": entry.version}


async def _find(ctx: ActionContext, cog: Any, guild_id: int, key: str = "backup_id") -> BackupEntry:
    backup_id = ctx.text(key, max_length=40)
    if not _ID.match(backup_id):
        raise ActionError("That backup does not exist.")
    entry = await cog.storage.get(guild_id, backup_id)
    if entry is None:
        raise ActionError("That backup does not exist.")
    return entry


def _components(ctx: ActionContext, allowed: set[str] | None = None) -> set[str]:
    raw = ctx.args.get("components")
    if raw is None:
        return set(allowed or COMPONENTS)
    if not isinstance(raw, list) or not all(isinstance(c, str) for c in raw):
        raise ActionError("Pick the parts to include.")
    chosen = {c for c in raw if c in COMPONENTS and (allowed is None or c in allowed)}
    if not chosen:
        raise ActionError("Pick at least one part.")
    return chosen


def _report(report: RestoreReport) -> dict[str, Any]:
    return {"dry_run": report.dry_run, "created": report.created, "updated": report.updated,
            "skipped": report.skipped, "failed": report.failed, "roles_added": report.roles_added,
            "roles_removed": report.roles_removed, "members_changed": report.members_changed,
            "steps": report.steps[-200:], "planned": report.planned[-500:], "errors": report.errors[-200:],
            "elapsed": round(report.elapsed, 1), "limited": report.limited}


@action("backups.list", "view", timeout=30)
async def listing(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    entries = await cog.storage.list(guild.id)
    settings = cog.settings
    return {"backups": [_entry(e) for e in entries], "components": {k: v[1] for k, v in COMPONENTS.items()},
            "max": settings.max_per_guild, "retention_days": settings.retention_days,
            "busy": cog.lock(guild.id).locked()}


@action("backups.create", "backups", timeout=300, summary=lambda a: f"back up server {a.get('guild_id')}")
async def create(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    label = ctx.text("label", default="", max_length=100).strip() or "Dashboard backup"
    ok, text = await cog.create_backup(guild, 0, label, components=_components(ctx))
    if not ok:
        raise ActionError(re.sub(r"^\S+ ", "", text) if text.startswith(("🟡", "🔴")) else text)
    entries = await cog.storage.list(guild.id)
    return {"backup": _entry(entries[0]) if entries else None}


@action("backups.update", "backups", timeout=20)
async def update(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    entry = await _find(ctx, cog, guild.id)
    fields: dict[str, Any] = {}
    if "pinned" in ctx.args:
        fields["pinned"] = int(ctx.flag("pinned"))
    if "label" in ctx.args:
        fields["label"] = ctx.text("label", max_length=100).strip() or entry.label
    if "note" in ctx.args:
        fields["note"] = ctx.text("note", default="", max_length=500).strip() or None
    if fields:
        await cog.storage.update(entry, **fields)
    return {"backup": _entry(await cog.storage.get(guild.id, entry.backup_id) or entry)}


@action("backups.delete", "backups", timeout=30, summary=lambda a: f"delete backup {a.get('backup_id')}")
async def delete(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    entry = await _find(ctx, cog, guild.id)
    if entry.pinned:
        raise ActionError("Unpin the backup before deleting it.")
    await cog.storage.delete(entry, 0)
    return {"deleted": entry.backup_id}


@action("backups.diff", "backups", timeout=120)
async def compare(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    entry = await _find(ctx, cog, guild.id)
    old = await cog.storage.load(entry)
    if ctx.args.get("other"):
        other = await _find(ctx, cog, guild.id, "other")
        new = await cog.storage.load(other)
        target = other.label
    else:
        new = await capture(guild, ctx.bot, {"roles", "categories", "channels", "emojis", "stickers"})
        target = None
    if old is None or new is None:
        raise ActionError("One of the backups could not be read.")
    return {"against": target, "sections": diff(old, new)}


@action("backups.preview", "backups", timeout=300)
async def preview(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    entry = await _find(ctx, cog, guild.id)
    snap = await cog.storage.load(entry)
    if snap is None:
        raise ActionError("The backup could not be read.")
    components = _components(ctx, set(snap.get("components") or COMPONENTS))
    report = await Restorer(ctx.bot, guild, snap, components, dry_run=True,
                            update_existing=ctx.flag("update_existing"),
                            sync_member_roles=ctx.flag("sync_member_roles")).run()
    return _report(report)


@action("backups.restore", "backups.restore", timeout=1800,
        summary=lambda a: f"restore backup {a.get('backup_id')} on server {a.get('guild_id')} "
        f"({', '.join(a.get('components') or ['everything'])})")
async def restore(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    guild = guild_of(ctx)
    entry = await _find(ctx, cog, guild.id)
    snap = await cog.storage.load(entry)
    if snap is None:
        raise ActionError("The backup could not be read.")
    components = _components(ctx, set(snap.get("components") or COMPONENTS))
    lock = cog.lock(guild.id)
    if lock.locked():
        raise ActionError("A backup or restore is already running for this server.")
    async with lock:
        report = await Restorer(ctx.bot, guild, snap, components, update_existing=ctx.flag("update_existing"),
                                sync_member_roles=ctx.flag("sync_member_roles"), progress=ctx.progress,
                                reason=f"ZDBF backup restore from the dashboard by {ctx.user.get('name')}").run()
    await cog.storage.audit(guild.id, "restore", 0, entry.backup_id,
                            f"dashboard {ctx.user.get('name')}: {','.join(sorted(components))} "
                            f"created={report.created} failed={report.failed}")
    return _report(report)
