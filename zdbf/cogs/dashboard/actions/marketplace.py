# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import hashlib
import time
from typing import Any

from ....core.storage import global_file_handler
from ....marketplace.client import Extension, KeyNotActivated, MarketplaceError, safety_scan
from ....marketplace.deps import (
    MISSING_RE,
    describe_command,
    install_packages,
    packages_for,
    required_packages,
)
from ....marketplace.key import ensure_key
from . import ActionContext, ActionError, action

PREVIEW_TTL = 900
PREVIEW_MAX = 20
_previews: dict[int, tuple[float, str, str]] = {}


def _cog(ctx: ActionContext) -> Any:
    cog = ctx.bot.get_cog("Marketplace")
    if cog is None:
        raise ActionError("The marketplace module is switched off on the bot ([modules] marketplace).")
    return cog


def _accepted(ctx: ActionContext, cog: Any) -> bool:
    return bool(set(cog.accepted) & set(ctx.bot.owner_id_set))


async def _find(cog: Any, ext_id: int) -> Extension:
    try:
        ext = await cog.client.get(ext_id)
    except MarketplaceError as exc:
        raise ActionError(str(exc)) from exc
    if ext is None:
        raise ActionError("That extension is no longer in the marketplace.")
    return ext


def _version_key(text: str) -> tuple[int, ...]:
    parts = []
    for piece in str(text).split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


@action("marketplace.list", "extensions", timeout=60)
async def listing(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    try:
        items = await cog.client.list(refresh=ctx.flag("refresh"))
    except MarketplaceError as exc:
        raise ActionError(str(exc)) from exc
    mgr = ctx.bot.ext
    loaded = set(ctx.bot.extensions)
    out = []
    for ext in items:
        record = cog.installed.get(ext.filename)
        on_disk = (mgr.directory / ext.filename).exists()
        out.append({
            "id": ext.id, "title": ext.title, "description": ext.description[:500], "details": ext.details[:4000],
            "version": ext.version, "creator": ext.creator, "official": ext.official, "status": ext.status,
            "date": ext.date, "changelog": ext.changelog[:2000], "file": ext.filename, "module": ext.module_name,
            "installed": record.get("version") if record else ("unknown" if on_disk else None),
            "loaded": mgr.module_for(ext.module_name) in loaded,
            "update": bool(record) and _version_key(ext.version) > _version_key(record.get("version", "0")),
        })
    age = cog.client.cache_age
    return {"items": out, "license": _accepted(ctx, cog), "age": round(age) if age is not None else None,
            "install": ctx.cog.policy.allows("marketplace"),
            "auto_packages": bool(ctx.bot.config.settings.marketplace.auto_install_packages)}


@action("marketplace.preview", "extensions", timeout=90)
async def preview(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    ext = await _find(cog, ctx.integer("id", minimum=1))
    key, _ = await ensure_key()
    try:
        source = await cog.client.download(ext, key)
    except KeyNotActivated as exc:
        raise ActionError("The ZSync ZDBF Key of this bot is not activated yet. The bot owner can see how with "
                          "/marketplace key in Discord.") from exc
    except MarketplaceError as exc:
        raise ActionError(str(exc)) from exc
    digest = hashlib.sha256(source.encode()).hexdigest()
    now = time.monotonic()
    for stale in [k for k, (at, _, _) in _previews.items() if now - at > PREVIEW_TTL]:
        _previews.pop(stale, None)
    while len(_previews) >= PREVIEW_MAX:
        _previews.pop(next(iter(_previews)))
    _previews[ext.id] = (now, digest, source)
    scan = safety_scan(source)
    packages = required_packages(scan, own_module=ext.module_name)
    return {
        "id": ext.id, "title": ext.title, "version": ext.version, "sha256": digest, "file": ext.filename,
        "path": str(ctx.bot.ext.directory / ext.filename), "exists": (ctx.bot.ext.directory / ext.filename).exists(),
        "bytes": len(source.encode()), "lines": scan.get("lines", 0), "ok": scan.get("ok", False),
        "error": scan.get("error"), "has_setup": scan.get("has_setup", False), "imports": scan.get("imports", [])[:40],
        "flags": scan.get("flags", []), "packages": packages, "optional": packages_for(scan.get("optional_imports", [])),
        "command": describe_command(packages) if packages else None, "license": _accepted(ctx, cog),
        "source": source[:200_000],
    }


@action("marketplace.install", "marketplace", timeout=900,
        summary=lambda a: f"install marketplace extension {a.get('id')}"
        + (" with its Python packages" if a.get("packages") else "") + (" and load it" if a.get("load") else ""))
async def install(ctx: ActionContext) -> dict[str, Any]:
    cog = _cog(ctx)
    if not _accepted(ctx, cog):
        raise ActionError("The bot owner has to accept the marketplace license once with /marketplace in Discord.")
    ext_id = ctx.integer("id", minimum=1)
    cached = _previews.get(ext_id)
    if cached is None or cached[1] != ctx.text("sha256", max_length=64):
        raise ActionError("The preview expired or the file changed. Open the extension again.")
    _, _, source = cached
    ext = await _find(cog, ext_id)
    scan = safety_scan(source)
    if not scan.get("ok"):
        raise ActionError(f"The file cannot be installed: {scan.get('error')}")
    mgr = ctx.bot.ext
    path = mgr.directory / ext.filename
    steps: list[dict[str, Any]] = []
    if not await global_file_handler.atomic_write(path, source):
        raise ActionError(f"Could not write {path}.")
    await cog.record_install(ext, source)
    _previews.pop(ext_id, None)
    steps.append({"ok": True, "text": f"Saved to {path}."})
    for problem in ctx.bot.plugins.preflight(ext.module_name, path):
        steps.append({"ok": False, "text": problem})
    loaded = False
    if ctx.flag("load"):
        packages = required_packages(scan, own_module=ext.module_name)
        if packages and ctx.flag("packages") and ctx.bot.config.settings.marketplace.auto_install_packages:
            pip = await install_packages(packages)
            if not pip.ok:
                steps.append({"ok": False, "text": f"Package install failed: {pip.error}", "output": pip.output})
                return {"steps": steps, "loaded": False, "file": ext.filename}
            steps.append({"ok": True, "text": f"Installed with {pip.tool}: {', '.join(pip.packages)}"})
        result = await mgr.reload(ext.module_name)
        loaded = result.ok
        if result.ok:
            steps.append({"ok": True, "text": f"{result.action.title()}ed in {result.elapsed_ms:.0f} ms."})
        else:
            missing = packages_for(MISSING_RE.findall(result.error or ""))
            steps.append({"ok": False, "text": result.error or "The extension did not load.",
                          "missing": missing})
    return {"steps": steps, "loaded": loaded, "file": ext.filename}
