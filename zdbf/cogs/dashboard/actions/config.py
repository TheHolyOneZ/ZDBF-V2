# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
import tomllib
import types
import typing
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from ....core.config import DEFAULT_CONFIG_PATH, Config, ConfigError, Settings
from ....core.storage import write_bytes_durable
from ..link import DATA_DIR
from . import ActionContext, ActionError, action

PROTECTED = ("dashboard", "modules.dashboard", "bot.owner_ids")
RESTART = ("bot.privileged_intents", "bot.intents", "shards", "cluster", "database", "logging")
HISTORY_DIR = DATA_DIR / "config-history"
HISTORY_KEEP = 10
TEXT_MAX = 256 * 1024
_SECTION = re.compile(r"^\s*\[\[?([A-Za-z0-9_.]+)\]\]?\s*(?:#.*)?$")
_KEY = re.compile(r"^\s*#?\s*([A-Za-z0-9_]+)\s*=\s*[^#]*?#\s*(.+?)\s*$")
_MISSING = object()


def _dig(data: Any, dotted: str) -> Any:
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(data, dict):
        return {prefix: data}
    out: dict[str, Any] = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            out.update(_flatten(value, name))
        else:
            out[name] = value
    return out


def changed_keys(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    a, b = _flatten(old), _flatten(new)
    return sorted(k for k in set(a) | set(b) if a.get(k, _MISSING) != b.get(k, _MISSING))


def protected_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    return [key for key in PROTECTED if _dig(old, key) != _dig(new, key)]


def touches_protected(key: str) -> bool:
    return any(key == p or key.startswith(f"{p}.") or p.startswith(f"{key}.") for p in PROTECTED)


def needs_restart(keys: list[str]) -> list[str]:
    return [k for k in keys if any(k == r or k.startswith(f"{r}.") for r in RESTART)]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _comments() -> dict[str, str]:
    text = resources.files("zdbf.core").joinpath("default_config.toml").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    section = ""
    for line in text.splitlines():
        head = _SECTION.match(line)
        if head:
            section = head.group(1)
            continue
        match = _KEY.match(line)
        if match and section:
            out.setdefault(f"{section}.{match.group(1)}", match.group(2))
    return out


def _describe(annotation: Any) -> dict[str, Any]:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        inner = [a for a in args if a is not type(None)]
        if len(inner) == 1:
            out = _describe(inner[0])
            out["optional"] = True
            return out
        return {"kind": "json"}
    if origin is Literal:
        return {"kind": "choice", "choices": [str(a) for a in args]}
    if annotation is bool:
        return {"kind": "bool"}
    if annotation is int:
        return {"kind": "int"}
    if annotation is float:
        return {"kind": "float"}
    if annotation is str:
        return {"kind": "text"}
    if origin is list and args and typing.get_origin(args[0]) is Literal:
        return {"kind": "multi", "choices": [str(a) for a in typing.get_args(args[0])]}
    if origin is list and args and args[0] in (str, int):
        return {"kind": "list", "item": "int" if args[0] is int else "text"}
    return {"kind": "json"}


def _bounds(info: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in getattr(info, "metadata", []):
        for attr, name in (("ge", "min"), ("gt", "min"), ("le", "max"), ("lt", "max")):
            value = getattr(item, attr, None)
            if isinstance(value, int | float):
                out[name] = value
    return out


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_plain(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump())
    return str(value)


def schema(config: Config) -> list[dict[str, Any]]:
    notes = _comments()
    overrides = _flatten(config.overrides)
    sections = []
    for name, info in Settings.model_fields.items():
        model = info.annotation
        fields = getattr(model, "model_fields", None)
        if not fields:
            continue
        items = []
        for field_name, field_info in fields.items():
            key = f"{name}.{field_name}"
            items.append({
                "key": key, **_describe(field_info.annotation), **_bounds(field_info),
                "default": _plain(field_info.default), "value": _plain(config.get(key)),
                "override": key in overrides, "note": notes.get(key), "protected": touches_protected(key),
            })
        sections.append({"name": name, "fields": items})
    return sections


def _history() -> list[dict[str, Any]]:
    if not HISTORY_DIR.is_dir():
        return []
    files = sorted(HISTORY_DIR.glob("config-*.toml"), reverse=True)
    return [{"name": f.name, "at": int(f.stat().st_mtime), "size": f.stat().st_size} for f in files[:HISTORY_KEEP]]


def _keep_copy(text: str) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    write_bytes_durable(HISTORY_DIR / f"config-{stamp}-{_sha(text)[:8]}.toml", text.encode())
    for old in sorted(HISTORY_DIR.glob("config-*.toml"), reverse=True)[HISTORY_KEEP:]:
        old.unlink(missing_ok=True)


def _parse(text: str) -> dict[str, Any]:
    try:
        _, data = Config.parse(text)
    except ConfigError as exc:
        raise ActionError(str(exc)) from exc
    return data


def _current(config: Config) -> tuple[str, dict[str, Any]]:
    text = config.path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        data = {}
    return text, data


def _write_summary(args: dict[str, Any]) -> str:
    text = args.get("text")
    try:
        old = tomllib.loads(Path(os.getenv("ZDBF_CONFIG") or DEFAULT_CONFIG_PATH).read_text(encoding="utf-8"))
        keys = changed_keys(old, tomllib.loads(text)) if isinstance(text, str) else []
    except (OSError, tomllib.TOMLDecodeError):
        keys = []
    shown = ", ".join(keys[:8]) + (f" and {len(keys) - 8} more" if len(keys) > 8 else "")
    return f"write config.toml ({shown or 'no recognisable changes'})"


def _set_summary(args: dict[str, Any]) -> str:
    if args.get("unset"):
        return f"remove the runtime override {args.get('key')}"
    return f"set {args.get('key')} = {str(args.get('value'))[:80]}"


@action("config.read", "config", timeout=20, approval=False)
async def read(ctx: ActionContext) -> dict[str, Any]:
    config = ctx.bot.config
    text, _ = await asyncio.to_thread(_current, config)
    return {
        "path": str(config.path), "text": text, "sha256": _sha(text), "sections": schema(config),
        "overrides": _plain(config.overrides), "protected": list(PROTECTED), "restart": list(RESTART),
        "history": await asyncio.to_thread(_history), "write": ctx.cog.policy.allows("config"),
    }


@action("config.validate", "config", timeout=20, approval=False)
async def validate(ctx: ActionContext) -> dict[str, Any]:
    text = ctx.text("text", max_length=TEXT_MAX)
    _, old = await asyncio.to_thread(_current, ctx.bot.config)
    try:
        _, data = Config.parse(text)
    except ConfigError as exc:
        return {"ok": False, "errors": str(exc).splitlines(), "changes": [], "protected": [], "restart": []}
    keys = changed_keys(old, data)
    blocked = protected_changes(old, data)
    return {"ok": not blocked, "errors": [], "changes": keys, "protected": blocked, "restart": needs_restart(keys)}


@action("config.backup", "config", timeout=20, approval=False)
async def backup(ctx: ActionContext) -> dict[str, Any]:
    name = ctx.text("name", max_length=80)
    if not re.fullmatch(r"config-[0-9]{8}-[0-9]{6}-[0-9a-f]{8}\.toml", name):
        raise ActionError("That copy does not exist.")
    path = HISTORY_DIR / name
    if not path.is_file():
        raise ActionError("That copy does not exist.")
    return {"name": name, "text": await asyncio.to_thread(path.read_text, encoding="utf-8")}


@action("config.write", "config", timeout=30, summary=_write_summary)
async def write(ctx: ActionContext) -> dict[str, Any]:
    config = ctx.bot.config
    text = ctx.text("text", max_length=TEXT_MAX)
    data = _parse(text)
    old_text, old = await asyncio.to_thread(_current, config)
    expect = ctx.args.get("expect")
    if isinstance(expect, str) and expect and expect != _sha(old_text) and not ctx.flag("force"):
        raise ActionError("config.toml changed on the bot since you opened it. Reload it, or save again to overwrite.")
    blocked = protected_changes(old, data)
    if blocked:
        raise ActionError("The dashboard cannot change " + ", ".join(blocked)
                          + ". Change it in config.toml on the bot machine or with /dashboard capabilities.")
    keys = changed_keys(old, data)
    await asyncio.to_thread(_keep_copy, old_text)
    await asyncio.to_thread(write_bytes_durable, config.path, text.encode())
    try:
        config.reload()
    except ConfigError as exc:
        await asyncio.to_thread(write_bytes_durable, config.path, old_text.encode())
        config.reload()
        raise ActionError(f"The bot could not use the new file, so the old one was put back: {exc}") from exc
    ctx.bot.prefix_cache.clear()
    return {"sha256": _sha(text), "changes": keys, "restart": needs_restart(keys),
            "history": await asyncio.to_thread(_history)}


@action("config.set", "config", timeout=20, summary=_set_summary)
async def set_value(ctx: ActionContext) -> dict[str, Any]:
    key = ctx.text("key", max_length=120).strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+", key):
        raise ActionError("That is not a setting name.")
    if touches_protected(key):
        raise ActionError(f"The dashboard cannot change {key}.")
    config = ctx.bot.config
    try:
        if ctx.flag("unset"):
            removed = await config.unset(key)
            if not removed:
                raise ActionError(f"{key} has no runtime override.")
        else:
            if "value" not in ctx.args:
                raise ActionError("missing value: value")
            await config.set(key, ctx.args["value"])
    except ConfigError as exc:
        raise ActionError(str(exc)) from exc
    ctx.bot.prefix_cache.clear()
    return {"key": key, "value": _plain(config.get(key)), "override": key in _flatten(config.overrides),
            "restart": bool(needs_restart([key]))}
