# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from .bot import ZDBFBot

log = logging.getLogger("zdbf.extensions")

__all__ = ["BUILTIN_MODULES", "ExtensionManager", "ExtensionResult"]

BUILTIN_MODULES: dict[str, str] = {
    "core": "zdbf.cogs.core",
    "admin": "zdbf.cogs.admin",
    "settings": "zdbf.cogs.settings",
    "diagnostics": "zdbf.cogs.diagnostics",
    "eventhooks": "zdbf.cogs.eventhooks",
    "plugins": "zdbf.cogs.plugins",
    "scheduler": "zdbf.cogs.scheduler",
    "automations": "zdbf.cogs.automations",
    "backup": "zdbf.cogs.backup",
    "shards": "zdbf.cogs.shards",
    "cluster": "zdbf.cogs.cluster",
    "marketplace": "zdbf.marketplace.cog",
}
ALWAYS_LOADED = ("zdbf.cogs.compat",)


class ExtensionError(Exception):
    pass


@dataclass(slots=True)
class ExtensionResult:
    name: str
    module: str
    ok: bool
    action: str
    elapsed_ms: float = 0.0
    error: str | None = None
    note: str | None = None


class ExtensionManager:
    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        settings = bot.config.settings.extensions
        self.directory = Path(settings.directory)
        self.package = self.directory.name
        self.load_times: dict[str, float] = {}
        self.failed: dict[str, str] = {}
        self._mtimes: dict[str, float] = {}
        self._watcher: asyncio.Task[None] | None = None

    def ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        root = str(self.directory.resolve().parent)
        if root not in sys.path:
            sys.path.insert(0, root)

    def module_for(self, name: str) -> str:
        name = name.strip().removesuffix(".py").replace("/", ".").replace("\\", ".")
        if name in BUILTIN_MODULES:
            return BUILTIN_MODULES[name]
        if name.startswith(("zdbf.", f"{self.package}.")):
            return name
        return f"{self.package}.{name.replace(' ', '_')}"

    def short_name(self, module: str) -> str:
        for key, mod in BUILTIN_MODULES.items():
            if mod == module:
                return key
        return module.removeprefix(f"{self.package}.")

    def path_for(self, module: str) -> Path | None:
        if not module.startswith(f"{self.package}."):
            return None
        rel = module.removeprefix(f"{self.package}.").replace(".", "/")
        file = self.directory / f"{rel}.py"
        if file.exists():
            return file
        pkg = self.directory / rel / "__init__.py"
        return pkg if pkg.exists() else None

    def discover(self) -> list[str]:
        self.ensure_directory()
        found: list[str] = []
        for path in sorted(self.directory.iterdir()):
            if path.name.startswith(("_", ".")):
                continue
            if path.is_file() and path.suffix == ".py":
                path = self._fix_spaces(path)
                found.append(f"{self.package}.{path.stem}")
            elif path.is_dir() and (path / "__init__.py").exists():
                found.append(f"{self.package}.{path.name}")
        return found

    def _fix_spaces(self, path: Path) -> Path:
        if " " not in path.stem:
            return path
        target = path.with_name(path.name.replace(" ", "_"))
        if target.exists():
            log.warning("both %s and %s exist - ignoring the one with spaces", path.name, target.name)
            return target
        path.rename(target)
        log.warning("renamed %s -> %s", path.name, target.name)
        return target

    def is_builtin(self, module: str) -> bool:
        return module.startswith("zdbf.")

    def _watch_paths(self, module: str) -> list[Path]:
        path = self.path_for(module)
        if path is None:
            return []
        if path.name == "__init__.py":
            return list(path.parent.rglob("*.py"))
        return [path]

    def _snapshot_mtime(self, module: str) -> None:
        paths = self._watch_paths(module)
        if paths:
            self._mtimes[module] = max(p.stat().st_mtime for p in paths if p.exists())

    async def load(self, name: str, *, validate: bool = True) -> ExtensionResult:
        module = self.module_for(name)
        short = self.short_name(module)
        if module in self.bot.extensions:
            return ExtensionResult(short, module, False, "load", error="already loaded")
        if not self.is_builtin(module) and self.path_for(module) is None:
            return ExtensionResult(short, module, False, "load", error="file not found")
        if validate and (path := self.path_for(module)) is not None:
            problems = self.bot.plugins.preflight(short, path)
            if problems:
                self.failed[module] = "; ".join(problems)
                await self.bot.alerts.send("plugins", f"`{short}` blocked: " + "; ".join(problems), "warning")
                return ExtensionResult(short, module, False, "load", error="; ".join(problems))
        start = time.perf_counter()
        try:
            await self.bot.load_extension(module)
        except commands.ExtensionError as exc:
            cause = exc.__cause__ or exc
            self.failed[module] = f"{type(cause).__name__}: {cause}"
            quiet = isinstance(exc, (commands.ExtensionNotFound, commands.NoEntryPointError))
            log.error("failed to load %s: %s", module, cause, exc_info=None if quiet else cause)
            return ExtensionResult(short, module, False, "load", error=self.failed[module])
        elapsed = (time.perf_counter() - start) * 1000
        self.failed.pop(module, None)
        self.load_times[short] = elapsed
        self._snapshot_mtime(module)
        if not self.is_builtin(module):
            self.bot.plugins.register_extension(short, module, elapsed)
        await self.bot.hooks.emit("extension_loaded", extension_name=module)
        self.bot.mark_tree_dirty()
        log.info("loaded %s (%.1f ms)", module, elapsed)
        return ExtensionResult(short, module, True, "load", elapsed)

    async def unload(self, name: str) -> ExtensionResult:
        module = self.module_for(name)
        short = self.short_name(module)
        if module == "zdbf.cogs.admin":
            return ExtensionResult(short, module, False, "unload", error="the admin module cannot be unloaded")
        try:
            await self.bot.unload_extension(module)
        except commands.ExtensionNotLoaded:
            return ExtensionResult(short, module, False, "unload", error="not loaded")
        self.bot.hooks.unregister_module(module)
        self.bot.plugins.unregister_plugin(short)
        self._mtimes.pop(module, None)
        await self.bot.hooks.emit("extension_unloaded", extension_name=module)
        self.bot.mark_tree_dirty()
        log.info("unloaded %s", module)
        return ExtensionResult(short, module, True, "unload")

    async def reload(self, name: str) -> ExtensionResult:
        module = self.module_for(name)
        short = self.short_name(module)
        if module not in self.bot.extensions:
            result = await self.load(name)
            result.action = "load"
            result.note = "was not loaded - loaded it instead"
            return result
        start = time.perf_counter()
        self.bot.hooks.unregister_module(module)
        try:
            await self.bot.reload_extension(module)
        except commands.ExtensionError as exc:
            cause = exc.__cause__ or exc
            log.error("failed to reload %s (previous version kept): %s", module, cause, exc_info=cause)
            return ExtensionResult(short, module, False, "reload", error=f"{type(cause).__name__}: {cause}",
                                   note="previous version is still running")
        elapsed = (time.perf_counter() - start) * 1000
        self.load_times[short] = elapsed
        self._snapshot_mtime(module)
        if not self.is_builtin(module):
            self.bot.plugins.register_extension(short, module, elapsed)
        await self.bot.hooks.emit("extension_reloaded", extension_name=module)
        await self.bot.hooks.emit("extension_loaded", extension_name=module)
        self.bot.mark_tree_dirty()
        log.info("reloaded %s (%.1f ms)", module, elapsed)
        return ExtensionResult(short, module, True, "reload", elapsed)

    async def load_builtin(self) -> list[ExtensionResult]:
        results = []
        for module in ALWAYS_LOADED:
            results.append(await self.load(module, validate=False))
        for key, module in BUILTIN_MODULES.items():
            if not self.bot.config.module_enabled(key):
                log.info("module disabled in config: %s", key)
                continue
            results.append(await self.load(module, validate=False))
        return results

    async def load_user_extensions(self) -> list[ExtensionResult]:
        blacklist = {b.removesuffix(".py") for b in self.bot.config.settings.extensions.blacklist}
        pending = [m for m in self.discover() if self.short_name(m) not in blacklist]
        results: list[ExtensionResult] = []
        blocked: dict[str, ExtensionResult] = {}
        while pending:
            progress = False
            blocked = {}
            for module in pending:
                res = await self.load(module)
                if not res.ok and res.error and res.error.startswith("Missing dependencies"):
                    blocked[module] = res
                else:
                    results.append(res)
                    progress = progress or res.ok
            pending = list(blocked)
            if not progress:
                break
        results.extend(blocked.values())
        return results

    def start_watcher(self) -> None:
        if self._watcher is None or self._watcher.done():
            self._watcher = asyncio.create_task(self._watch(), name="zdbf-hot-reload")

    async def stop_watcher(self) -> None:
        if self._watcher is not None:
            self._watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher
            self._watcher = None

    async def _watch(self) -> None:
        interval = self.bot.config.settings.extensions.hot_reload_interval
        while True:
            await asyncio.sleep(interval)
            for module in list(self.bot.extensions):
                if self.is_builtin(module):
                    continue
                paths = [p for p in self._watch_paths(module) if p.exists()]
                if not paths:
                    continue
                mtime = max(p.stat().st_mtime for p in paths)
                if mtime > self._mtimes.get(module, mtime):
                    self._mtimes[module] = mtime
                    res = await self.reload(module)
                    if res.ok:
                        log.info("hot-reloaded %s", module)
                    else:
                        await self.bot.alerts.send("extensions", f"Hot reload of `{res.name}` failed: {res.error}",
                                                   "error")
