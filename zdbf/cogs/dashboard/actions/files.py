# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any

from ....core.storage import global_file_handler, write_bytes_durable
from ..link import DATA_DIR
from ..sandbox import Sandbox, SandboxError
from . import ActionContext, ActionError, action

CHUNK = 768 * 1024
LIST_MAX = 2000
TRASH_DIR = DATA_DIR / "trash"
UPLOAD_DIR = DATA_DIR / "uploads"
TRASH_KEEP = 200
TRASH_DAYS = 30
UPLOAD_TTL = 3600
_UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
_NAME = re.compile(r"^[^/\\:*?\"<>|\x00-\x1f]{1,255}$")
_trash_lock = asyncio.Lock()


def _box(ctx: ActionContext) -> Sandbox:
    return ctx.cog.sandbox


def _rel(box: Sandbox, path: Path) -> str:
    return box.relative(path)


def _entry(box: Sandbox, path: Path) -> dict[str, Any]:
    st = path.stat()
    folder = path.is_dir()
    return {"name": path.name, "path": _rel(box, path), "dir": folder, "size": 0 if folder else st.st_size,
            "mtime": int(st.st_mtime)}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decode(raw: Any) -> bytes:
    if not isinstance(raw, str):
        raise ActionError("The file data could not be read.")
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ActionError("The file data could not be read.") from exc


def _name(value: Any) -> str:
    if not isinstance(value, str) or not _NAME.match(value) or value.strip() in ("", ".", ".."):
        raise ActionError("That name is not allowed.")
    return value.strip()


def _size_text(args: dict[str, Any]) -> str:
    size = args.get("size")
    if isinstance(size, int) and size >= 0:
        return f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"
    return "?"


def module_for_file(bot: Any, path: Path) -> str | None:
    mgr = bot.ext
    real = path.resolve()
    for module in list(bot.extensions):
        if mgr.is_builtin(module):
            continue
        file = mgr.path_for(module)
        if file is None:
            continue
        file = file.resolve()
        if file == real or (file.name == "__init__.py" and file.parent in real.parents):
            return module
    return None


async def reload_after_save(ctx: ActionContext, path: Path) -> dict[str, Any] | None:
    module = module_for_file(ctx.bot, path)
    if module is None:
        return None
    if not ctx.cog.policy.allows("extensions"):
        return {"module": module, "ok": False, "error": "The capability `extensions` is switched off on the bot."}
    result = await ctx.bot.ext.reload(module)
    return {"module": result.name, "ok": result.ok, "error": result.error, "note": result.note,
            "ms": round(result.elapsed_ms, 1)}


@action("files.roots", "files.read", timeout=15)
async def roots(ctx: ActionContext) -> dict[str, Any]:
    box = _box(ctx)
    out = []
    for name in box.root_names():
        try:
            real = box.resolve(name)
        except SandboxError as exc:
            out.append({"path": name, "ok": False, "error": str(exc)})
            continue
        out.append({"path": name, "ok": real.is_dir(), "error": None if real.is_dir() else "the folder does not exist"})
    return {"roots": out, "max_bytes": box.max_bytes, "chunk": CHUNK,
            "write": ctx.cog.policy.allows("files.write"), "reload": ctx.cog.policy.allows("extensions")}


@action("files.list", "files.read", timeout=20)
async def listing(ctx: ActionContext) -> dict[str, Any]:
    box = _box(ctx)
    folder = box.resolve(ctx.text("path", max_length=1024))
    if not folder.is_dir():
        raise ActionError("That folder does not exist.")

    def scan() -> tuple[list[dict[str, Any]], bool]:
        items = []
        children = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        for child in children:
            if len(items) >= LIST_MAX:
                return items, True
            if not box.visible(child):
                continue
            try:
                items.append(_entry(box, child))
            except OSError:
                continue
        return items, False

    items, cut = await asyncio.to_thread(scan)
    return {"path": _rel(box, folder), "items": items, "cut": cut}


@action("files.read", "files.read", timeout=60)
async def read(ctx: ActionContext) -> dict[str, Any]:
    box = _box(ctx)
    path = box.resolve(ctx.text("path", max_length=1024))
    if not path.is_file():
        raise ActionError("That file does not exist.")
    offset = ctx.integer("offset", default=0, minimum=0)

    def load() -> dict[str, Any]:
        st = path.stat()
        box.check_size(st.st_size)
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read(CHUNK)
        out: dict[str, Any] = {
            "path": _rel(box, path), "size": st.st_size, "mtime": int(st.st_mtime),
            "version": f"{st.st_size}-{st.st_mtime_ns}", "offset": offset,
            "data": base64.b64encode(data).decode(), "eof": offset + len(data) >= st.st_size,
        }
        if offset == 0:
            out["sha256"] = _sha(path)
        return out

    return await asyncio.to_thread(load)


def _clean_uploads() -> None:
    if not UPLOAD_DIR.is_dir():
        return
    cutoff = time.time() - UPLOAD_TTL
    for part in UPLOAD_DIR.glob("*.part"):
        try:
            if part.stat().st_mtime < cutoff:
                part.unlink()
        except OSError:
            continue


def _upload_path(upload: str) -> Path:
    if not _UPLOAD_ID.match(upload):
        raise ActionError("That upload is not valid.")
    return UPLOAD_DIR / f"{upload}.part"


@action("files.stage", "files.write", timeout=60, approval=False)
async def stage(ctx: ActionContext) -> dict[str, Any]:
    box = _box(ctx)
    upload = ctx.text("upload", max_length=32)
    total = ctx.integer("total", minimum=1)
    box.check_size(total)
    offset = ctx.integer("offset", minimum=0)
    data = _decode(ctx.args.get("data"))
    if len(data) > CHUNK:
        raise ActionError("That piece of the upload is too large.")
    part = _upload_path(upload)

    def append() -> int:
        _clean_uploads()
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        have = part.stat().st_size if part.exists() else 0
        if offset != have:
            raise ActionError("The upload got out of step. Start it again.")
        if have + len(data) > total:
            raise ActionError("The upload is larger than announced.")
        with part.open("ab") as fh:
            fh.write(data)
        return have + len(data)

    return {"received": await asyncio.to_thread(append)}


async def _trash(ctx: ActionContext, path: Path, reason: str, *, held: bool = False) -> dict[str, Any]:
    box = _box(ctx)
    entry_id = f"{int(time.time())}-{secrets.token_hex(4)}"
    rel = _rel(box, path)

    def move() -> dict[str, Any]:
        target = TRASH_DIR / entry_id
        target.mkdir(parents=True, exist_ok=True)
        folder = path.is_dir()
        size = (sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if folder else path.stat().st_size)
        if reason == "replaced":
            shutil.copy2(path, target / path.name)
        else:
            shutil.move(str(path), str(target / path.name))
        return {"id": entry_id, "path": rel, "name": path.name, "dir": folder, "size": size, "reason": reason,
                "at": int(time.time()), "by": str(ctx.user.get("name") or "")[:64]}

    async def store() -> dict[str, Any]:
        entry = await asyncio.to_thread(move)
        index = await asyncio.to_thread(_read_index)
        index.insert(0, entry)
        await asyncio.to_thread(_write_index, _prune(index))
        return entry

    if held:
        return await store()
    async with _trash_lock:
        return await store()


def _read_index() -> list[dict[str, Any]]:
    try:
        data = json.loads((TRASH_DIR / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict) and isinstance(e.get("id"), str)] if isinstance(data, list) else []


def _write_index(index: list[dict[str, Any]]) -> None:
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    write_bytes_durable(TRASH_DIR / "index.json", json.dumps(index, indent=1).encode())


def _prune(index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = time.time() - TRASH_DAYS * 86400
    keep, drop = [], []
    for entry in index:
        (keep if len(keep) < TRASH_KEEP and entry.get("at", 0) >= cutoff else drop).append(entry)
    for entry in drop:
        shutil.rmtree(TRASH_DIR / entry["id"], ignore_errors=True)
    return keep


@action("files.write", "files.write", timeout=120,
        summary=lambda a: f"{'create' if a.get('create') else 'replace'} {a.get('path')} ({_size_text(a)})")
async def write(ctx: ActionContext) -> dict[str, Any]:
    box = _box(ctx)
    path = box.resolve(ctx.text("path", max_length=1024))
    create = ctx.flag("create")
    if not path.parent.is_dir():
        raise ActionError("The folder for that file does not exist.")
    if path.is_dir():
        raise ActionError("That path is a folder.")
    exists = path.exists()
    if create and exists:
        raise ActionError("A file with that name already exists.")
    if not create and not exists:
        raise ActionError("That file no longer exists. Save it as a new file.")
    upload = ctx.args.get("upload")
    part: Path | None = None
    if isinstance(upload, str) and upload:
        part = _upload_path(upload)
        if not part.is_file():
            raise ActionError("The upload was not found. Start it again.")
        size = part.stat().st_size
        expected = ctx.integer("size", minimum=0)
        if size != expected:
            raise ActionError("The upload is incomplete. Start it again.")
        box.check_size(size)
        data = None
    else:
        data = _decode(ctx.args.get("data"))
        box.check_size(len(data))
    expect = ctx.args.get("expect")
    if exists and isinstance(expect, str) and expect and not ctx.flag("force"):
        current = await asyncio.to_thread(_sha, path)
        if current != expect:
            raise ActionError("The file changed on the bot since you opened it. Reload it, or save again to overwrite.")
    trashed = await _trash(ctx, path, "replaced") if exists else None
    if part is not None:
        await asyncio.to_thread(os.replace, part, path)
    else:
        assert data is not None
        await asyncio.to_thread(write_bytes_durable, path, data)
    global_file_handler.invalidate_cache(str(path))
    reloaded = await reload_after_save(ctx, path) if ctx.flag("reload") else None
    st = path.stat()
    return {"path": _rel(box, path), "size": st.st_size, "mtime": int(st.st_mtime),
            "sha256": await asyncio.to_thread(_sha, path), "trash": trashed["id"] if trashed else None,
            "reload": reloaded}


@action("files.mkdir", "files.write", timeout=15, approval=False)
async def mkdir(ctx: ActionContext) -> dict[str, Any]:
    box = _box(ctx)
    parent = box.resolve(ctx.text("path", max_length=1024))
    if not parent.is_dir():
        raise ActionError("That folder does not exist.")
    target = box.resolve(f"{_rel(box, parent)}/{_name(ctx.args.get('name'))}")
    if target.exists():
        raise ActionError("Something with that name already exists.")
    target.mkdir()
    return {"path": _rel(box, target)}


@action("files.rename", "files.write", timeout=30,
        summary=lambda a: f"rename {a.get('path')} to {a.get('name')}")
async def rename(ctx: ActionContext) -> dict[str, Any]:
    box = _box(ctx)
    source = box.resolve(ctx.text("path", max_length=1024))
    if not source.exists():
        raise ActionError("That file no longer exists.")
    if source.resolve() in [box.resolve(r) for r in box.root_names()]:
        raise ActionError("A root folder cannot be renamed.")
    target = box.resolve(f"{_rel(box, source.parent)}/{_name(ctx.args.get('name'))}")
    if target.exists():
        raise ActionError("Something with that name already exists.")
    await asyncio.to_thread(source.rename, target)
    return {"path": _rel(box, target)}


@action("files.delete", "files.write", timeout=60, summary=lambda a: f"delete {a.get('path')} (kept in the trash)")
async def delete(ctx: ActionContext) -> dict[str, Any]:
    box = _box(ctx)
    path = box.resolve(ctx.text("path", max_length=1024))
    if not path.exists():
        raise ActionError("That file no longer exists.")
    if path.resolve() in [box.resolve(r) for r in box.root_names()]:
        raise ActionError("A root folder cannot be deleted.")
    module = module_for_file(ctx.bot, path)
    entry = await _trash(ctx, path, "deleted")
    return {"trash": entry["id"], "loaded_module": ctx.bot.ext.short_name(module) if module else None}


@action("files.trash", "files.read", timeout=15)
async def trash(ctx: ActionContext) -> dict[str, Any]:
    async with _trash_lock:
        index = await asyncio.to_thread(_read_index)
    return {"items": index, "days": TRASH_DAYS, "keep": TRASH_KEEP}


@action("files.restore", "files.write", timeout=60, summary=lambda a: f"restore {a.get('id')} from the trash")
async def restore(ctx: ActionContext) -> dict[str, Any]:
    box = _box(ctx)
    entry_id = ctx.text("id", max_length=40)
    async with _trash_lock:
        index = await asyncio.to_thread(_read_index)
        entry = next((e for e in index if e["id"] == entry_id), None)
        if entry is None:
            raise ActionError("That item is no longer in the trash.")
        target = box.resolve(entry["path"])
        source = TRASH_DIR / entry["id"] / entry["name"]
        if not source.exists():
            raise ActionError("The trashed copy is missing.")
        if not target.parent.is_dir():
            raise ActionError("The folder it came from no longer exists.")
        if target.exists():
            if entry.get("dir") or target.is_dir():
                raise ActionError("Something with that name exists again. Rename or delete it first.")
            await _trash(ctx, target, "replaced", held=True)
            index = await asyncio.to_thread(_read_index)
        await asyncio.to_thread(shutil.move, str(source), str(target))
        shutil.rmtree(TRASH_DIR / entry["id"], ignore_errors=True)
        await asyncio.to_thread(_write_index, [e for e in index if e["id"] != entry_id])
    return {"path": entry["path"]}


ARCHIVE_DIR = DATA_DIR / "archives"
ARCHIVE_MAX = 64 * 1024 * 1024
ARCHIVE_TTL = 3600
_ARCHIVE_ID = re.compile(r"^[0-9a-f]{32}$")


def _clean_archives() -> None:
    if not ARCHIVE_DIR.is_dir():
        return
    cutoff = time.time() - ARCHIVE_TTL
    for item in ARCHIVE_DIR.glob("*.zip"):
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink()
        except OSError:
            continue


@action("files.archive", "files.read", timeout=300)
async def archive(ctx: ActionContext) -> dict[str, Any]:
    import zipfile

    box = _box(ctx)
    folder = box.resolve(ctx.text("path", max_length=1024))
    if not folder.is_dir():
        raise ActionError("That folder does not exist.")
    archive_id = secrets.token_hex(16)

    def build() -> tuple[int, int]:
        _clean_archives()
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        target = ARCHIVE_DIR / f"{archive_id}.zip"
        total = count = 0
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(folder.rglob("*")):
                if not path.is_file() or not box.visible(path) or any(p.name == "__pycache__" for p in path.parents):
                    continue
                if any(not box.visible(parent) for parent in path.parents if folder in parent.parents):
                    continue
                total += path.stat().st_size
                if total > ARCHIVE_MAX:
                    target.unlink(missing_ok=True)
                    raise ActionError(f"The folder is larger than {ARCHIVE_MAX // (1024 * 1024)} MB.")
                zf.write(path, path.relative_to(folder.parent).as_posix())
                count += 1
        return target.stat().st_size, count

    size, count = await asyncio.to_thread(build)
    return {"id": archive_id, "size": size, "files": count, "name": f"{folder.name}.zip", "chunk": CHUNK}


@action("files.archive_read", "files.read", timeout=60)
async def archive_read(ctx: ActionContext) -> dict[str, Any]:
    archive_id = ctx.text("id", max_length=32)
    if not _ARCHIVE_ID.match(archive_id):
        raise ActionError("That archive does not exist.")
    path = ARCHIVE_DIR / f"{archive_id}.zip"
    offset = ctx.integer("offset", default=0, minimum=0)

    def load() -> dict[str, Any]:
        if not path.is_file():
            raise ActionError("The archive expired. Make it again.")
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read(CHUNK)
        done = offset + len(data) >= size
        if done:
            path.unlink(missing_ok=True)
        return {"size": size, "offset": offset, "data": base64.b64encode(data).decode(), "eof": done}

    return await asyncio.to_thread(load)
