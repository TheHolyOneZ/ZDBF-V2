# ZSync Marketplace client - Copyright (c) 2025-2026 TheHolyOneZ (TheZ). All rights reserved.
# Licensed under the ZSync Marketplace License (LICENSE-MARKETPLACE), NOT the Apache License.
# The names ZSync, ZDBF, Zoryx, TheHolyOneZ and TheZ must not be removed or altered.
from __future__ import annotations

import ast
import asyncio
import datetime as dt
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

log = logging.getLogger("zdbf.marketplace")

KEY_PARAM = "zygnalid"
USER_AGENT = "ZDBF-Marketplace/2.0 (+https://zsync.eu/extension/)"

__all__ = ["KEY_PARAM", "Extension", "MarketplaceClient", "MarketplaceError", "safety_scan"]


class MarketplaceError(Exception):
    pass


class KeyNotActivated(MarketplaceError):
    pass


@dataclass(frozen=True)
class Extension:
    id: int
    title: str
    description: str
    details: str
    version: str
    creator: str
    owner_type: str
    status: str
    date: str
    changelog: str
    file_type: str
    custom_url: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Extension:
        return cls(
            id=int(raw.get("id", 0)), title=str(raw.get("title", "Untitled")),
            description=str(raw.get("description") or ""), details=str(raw.get("details") or "").replace("\r\n", "\n"),
            version=str(raw.get("version") or "1.0.0"), creator=str(raw.get("creator") or "unknown"),
            owner_type=str(raw.get("owner_type") or "user"), status=str(raw.get("status") or "unknown").lower(),
            date=str(raw.get("date") or ""), changelog=str(raw.get("changelog") or "").replace("\r\n", "\n"),
            file_type=str(raw.get("fileType") or "py"), custom_url=str(raw.get("customUrl") or ""),
        )

    @property
    def filename(self) -> str:
        name = re.sub(r"[^\w\-.]", "", f"{self.title.replace(' ', '_').lower()}.{self.file_type}")
        return name or f"extension_{self.id}.py"

    @property
    def module_name(self) -> str:
        return self.filename.rsplit(".", 1)[0]

    @property
    def official(self) -> bool:
        return self.owner_type == "admin"

    @property
    def released(self) -> dt.datetime | None:
        try:
            return dt.datetime.fromisoformat(self.date).replace(tzinfo=dt.UTC)
        except ValueError:
            return None

    @property
    def status_emoji(self) -> str:
        return {"working": "🟢", "beta": "🟡", "broken": "🔴"}.get(self.status, "⚪")


class MarketplaceClient:
    def __init__(self, api_url: str, download_url: str, cache_minutes: int = 10) -> None:
        self.api_url = api_url
        self.download_url = download_url
        self.cache_seconds = cache_minutes * 60
        self._session: aiohttp.ClientSession | None = None
        self._cache: list[Extension] = []
        self._cached_at = 0.0

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT},
                                                  timeout=aiohttp.ClientTimeout(total=45))
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    @property
    def cache_age(self) -> float | None:
        return time.monotonic() - self._cached_at if self._cache else None

    async def list(self, *, refresh: bool = False) -> list[Extension]:
        if self._cache and not refresh and time.monotonic() - self._cached_at < self.cache_seconds:
            return self._cache
        session = await self.session()
        try:
            async with session.get(self.api_url) as resp:
                if resp.status == 429:
                    raise MarketplaceError("The marketplace is rate limiting requests - try again in a minute.")
                if resp.status != 200:
                    raise MarketplaceError(f"Marketplace API returned HTTP {resp.status}.")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as exc:
            if self._cache:
                log.warning("marketplace unreachable, serving cached list: %s", exc)
                return self._cache
            raise MarketplaceError(f"Could not reach the marketplace: {exc}") from exc
        if not isinstance(data, dict) or not data.get("success"):
            raise MarketplaceError("The marketplace API reported an error.")
        self._cache = [Extension.from_api(e) for e in data.get("extensions", []) if isinstance(e, dict)]
        self._cached_at = time.monotonic()
        return self._cache

    async def get(self, ref: str | int) -> Extension | None:
        items = await self.list()
        text = str(ref).strip().lower()
        if text.isdigit():
            return next((e for e in items if e.id == int(text)), None)
        return next((e for e in items if e.title.lower() == text or e.module_name == text), None) or next(
            (e for e in items if text in e.title.lower()), None)

    async def search(self, query: str) -> list[Extension]:
        words = query.lower().split()
        items = await self.list()

        def score(e: Extension) -> int:
            hay_title, hay = e.title.lower(), f"{e.description} {e.details} {e.creator}".lower()
            return sum((5 if w in hay_title else 0) + (1 if w in hay else 0) for w in words)

        hits = [(score(e), e) for e in items]
        return [e for s, e in sorted(hits, key=lambda x: (-x[0], x[1].title.lower())) if s > 0]

    def _download_url(self, ext: Extension, key: str) -> str:
        if ext.custom_url.startswith("http"):
            sep = "&" if "?" in ext.custom_url else "?"
            return f"{ext.custom_url}{sep}{KEY_PARAM}={key}"
        return f"{self.download_url}?id={ext.id}&{KEY_PARAM}={key}"

    async def download(self, ext: Extension, key: str, *, retries: int = 3) -> str:
        session = await self.session()
        url = self._download_url(ext, key)
        last = "unknown error"
        for attempt in range(retries):
            try:
                async with session.get(url) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(min(int(resp.headers.get("Retry-After", 10)), 60))
                        last = "rate limited"
                        continue
                    text = await resp.text()
                    if resp.status != 200:
                        _raise_for_body(resp.status, text)
            except (aiohttp.ClientError, TimeoutError) as exc:
                last = str(exc)
                await asyncio.sleep(2 ** attempt)
                continue
            if _looks_like_key_error(text):
                raise KeyNotActivated(_server_message(text) or "key not activated")
            if not text.strip():
                raise MarketplaceError("The marketplace returned an empty file.")
            return text
        raise MarketplaceError(f"Download failed after {retries} attempts: {last}")


def _server_message(text: str) -> str | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return str(data.get("message")) if isinstance(data, dict) and data.get("message") else None


def _looks_like_key_error(text: str) -> bool:
    lowered = text[:800].lower()
    return ("invalid" in lowered and ("zygnalid" in lowered or "key" in lowered)) or "not activated" in lowered


def _raise_for_body(status: int, text: str) -> None:
    if _looks_like_key_error(text):
        raise KeyNotActivated(_server_message(text) or "key not activated")
    message = _server_message(text)
    raise MarketplaceError(f"Download failed (HTTP {status})" + (f": {message}" if message else ""))


RISKY_CALLS = {"eval", "exec", "compile", "__import__", "system", "popen", "rmtree", "remove", "unlink",
               "check_output", "Popen", "run", "call"}
RISKY_MODULES = {"subprocess", "ctypes", "socket", "shutil", "pickle", "marshal"}


IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _catches_import_error(node: ast.Try) -> bool:
    for handler in node.handlers:
        if handler.type is None:
            return True
        types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        if any(getattr(t, "id", getattr(t, "attr", "")) in IMPORT_ERRORS for t in types):
            return True
    return False


def _is_type_checking(node: ast.If) -> bool:
    test = node.test
    return getattr(test, "id", getattr(test, "attr", "")) == "TYPE_CHECKING"


def _top_modules(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Import):
        return {a.name.split(".")[0] for a in node.names}
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        return {node.module.split(".")[0]}
    return set()


def optional_imports(tree: ast.AST) -> set[str]:
    optional: set[str] = set()
    for node in ast.walk(tree):
        guarded: list[ast.stmt] = []
        if isinstance(node, (ast.Try, ast.TryStar)) and _catches_import_error(node):
            guarded = node.body
        elif isinstance(node, ast.If) and _is_type_checking(node):
            guarded = node.body
        for stmt in guarded:
            for inner in ast.walk(stmt):
                optional |= _top_modules(inner)
    return optional


def safety_scan(source: str) -> dict[str, Any]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"ok": False, "error": f"syntax error on line {exc.lineno}: {exc.msg}", "imports": [], "flags": [],
                "optional_imports": []}
    imports: set[str] = set()
    flags: set[str] = set()
    has_setup = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name in RISKY_CALLS and not (name in ("run", "call", "remove") and isinstance(node.func, ast.Attribute)
                                            and getattr(node.func.value, "id", "") not in ("subprocess", "os")):
                flags.add(f"calls `{name}()`")
        elif isinstance(node, ast.AsyncFunctionDef) and node.name == "setup":
            has_setup = True
    flags.update(f"imports `{m}`" for m in imports & RISKY_MODULES)
    optional = optional_imports(tree)
    return {"ok": True, "imports": sorted(imports), "flags": sorted(flags), "has_setup": has_setup,
            "optional_imports": sorted(optional & imports), "lines": source.count("\n") + 1}
