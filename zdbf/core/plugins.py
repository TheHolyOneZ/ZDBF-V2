# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import ast
import asyncio
import datetime as dt
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .bot import ZDBFBot

log = logging.getLogger("zdbf.plugins")

__all__ = ["PluginMetadata", "PluginRegistry", "compare_versions", "read_static_metadata"]

_DUNDERS = {
    "__version__": "version",
    "__author__": "author",
    "__description__": "description",
    "__dependencies__": "dependencies",
    "__conflicts__": "conflicts_with",
    "__provides_hooks__": "provides_hooks",
    "__listens_to_hooks__": "listens_to_hooks",
}
_OP_RE = re.compile(r"^\s*(>=|<=|==|!=|>|<|~=)?\s*(.*)$")


def parse_version(v: str) -> tuple[int, ...]:
    nums = tuple(int(x) for x in re.findall(r"\d+", str(v)))
    return nums or (0,)


def compare_versions(found: str, spec: str) -> bool:
    spec = (spec or "").strip()
    if not spec or spec in ("*", ">=0.0.0"):
        return True
    m = _OP_RE.match(spec)
    assert m is not None
    op, wanted = m.group(1) or "==", m.group(2)
    a, b = parse_version(found), parse_version(wanted)
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    match op:
        case ">=":
            return a >= b
        case "<=":
            return a <= b
        case ">":
            return a > b
        case "<":
            return a < b
        case "!=":
            return a != b
        case "~=":
            return a[0] == b[0] and a >= b
        case _:
            return a == b


def _normalise_deps(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v or "") for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return {str(v): "" for v in value}
    return {}


@dataclass
class PluginMetadata:
    name: str
    version: str = "unknown"
    author: str = "unknown"
    description: str = "No description"
    dependencies: dict[str, str] = field(default_factory=dict)
    conflicts_with: set[str] = field(default_factory=set)
    provides_hooks: list[str] = field(default_factory=list)
    listens_to_hooks: list[str] = field(default_factory=list)
    commands: set[str] = field(default_factory=set)
    cogs: set[str] = field(default_factory=set)
    file_path: str | None = None
    module: str | None = None
    loaded_at: float = field(default_factory=time.time)
    load_time_ms: float = 0.0
    scan_errors: list[str] = field(default_factory=list)

    def apply(self, raw: dict[str, Any]) -> None:
        for dunder, attr in _DUNDERS.items():
            if dunder not in raw:
                continue
            value = raw[dunder]
            match attr:
                case "dependencies":
                    self.dependencies = _normalise_deps(value)
                case "conflicts_with":
                    self.conflicts_with = {str(v) for v in value} if isinstance(value, (list, tuple, set)) else set()
                case "provides_hooks" | "listens_to_hooks":
                    setattr(self, attr, [str(v) for v in value] if isinstance(value, (list, tuple, set)) else [])
                case _:
                    setattr(self, attr, str(value))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["conflicts_with"] = sorted(self.conflicts_with)
        d["commands"] = sorted(self.commands)
        d["cogs"] = sorted(self.cogs)
        return d


def read_static_metadata(path: str | Path) -> dict[str, Any]:
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return {}
    found: dict[str, Any] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        for t in targets:
            if isinstance(t, ast.Name) and t.id in _DUNDERS and value is not None:
                try:
                    found[t.id] = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    continue
    return found


class PluginRegistry:
    KV_KEY = "plugins.settings"
    EXPORT_PATH = Path("data/plugin_registry.json")

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self.plugins: dict[str, PluginMetadata] = {}
        self.enforce_dependencies = True
        self.enforce_conflicts = True
        self._export_task: asyncio.Task[None] | None = None

    async def export(self) -> bool:
        from .storage import global_file_handler

        data = {
            "last_updated": dt.datetime.now(dt.UTC).isoformat(),
            "total_plugins": len(self.plugins),
            "enforcement": {"dependencies": self.enforce_dependencies, "conflicts": self.enforce_conflicts},
            "plugins": {name: meta.to_dict() for name, meta in sorted(self.plugins.items())},
        }
        return await global_file_handler.atomic_write_json(self.EXPORT_PATH, data)

    def _schedule_export(self) -> None:
        async def later() -> None:
            await asyncio.sleep(1)
            try:
                await self.export()
            except Exception:
                log.exception("could not export the plugin registry")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._export_task is not None and not self._export_task.done():
            self._export_task.cancel()
        self._export_task = loop.create_task(later())

    async def load_settings(self) -> None:
        cfg = await self.bot.db.kv_get(self.KV_KEY, {})
        self.enforce_dependencies = cfg.get("enforce_dependencies", True)
        self.enforce_conflicts = cfg.get("enforce_conflicts", True)

    async def save_settings(self) -> None:
        await self.bot.db.kv_set(
            self.KV_KEY,
            {"enforce_dependencies": self.enforce_dependencies, "enforce_conflicts": self.enforce_conflicts},
        )
        self._schedule_export()

    def get(self, name: str) -> PluginMetadata | None:
        return self.plugins.get(name)

    def all(self) -> dict[str, PluginMetadata]:
        return dict(self.plugins)

    def check_dependencies(self, meta: PluginMetadata) -> list[str]:
        problems = []
        for dep, spec in meta.dependencies.items():
            other = self.plugins.get(dep)
            if other is None:
                problems.append(f"{dep} (not loaded)")
            elif not compare_versions(other.version, spec):
                problems.append(f"{dep} (requires {spec}, found {other.version})")
        return problems

    def detect_conflicts(self, meta: PluginMetadata) -> list[str]:
        hits = {c for c in meta.conflicts_with if c in self.plugins and c != meta.name}
        hits |= {n for n, m in self.plugins.items() if n != meta.name and meta.name in m.conflicts_with}
        return sorted(hits)

    def find_cycle(self, name: str, pending: PluginMetadata | None = None) -> list[str] | None:
        graph = {n: list(m.dependencies) for n, m in self.plugins.items()}
        if pending is not None:
            graph[pending.name] = list(pending.dependencies)

        def visit(node: str, path: list[str]) -> list[str] | None:
            if node in path:
                return [*path[path.index(node):], node]
            for nxt in graph.get(node, ()):
                if (cycle := visit(nxt, [*path, node])) is not None:
                    return cycle
            return None

        return visit(name, [])

    def validate(self, meta: PluginMetadata) -> list[str]:
        errors = []
        if self.enforce_dependencies and (missing := self.check_dependencies(meta)):
            errors.append("Missing dependencies: " + ", ".join(missing))
        if self.enforce_conflicts and (conflicts := self.detect_conflicts(meta)):
            errors.append("Conflicts with: " + ", ".join(conflicts))
        if (cycle := self.find_cycle(meta.name, meta)) is not None:
            errors.append("Circular dependency: " + " -> ".join(cycle))
        return errors

    def preflight(self, name: str, path: str | Path) -> list[str]:
        meta = PluginMetadata(name=name, file_path=str(path))
        meta.apply(read_static_metadata(path))
        return self.validate(meta)

    async def register_plugin(
        self,
        name: str,
        version: str = "unknown",
        author: str = "unknown",
        description: str = "No description",
        dependencies: dict[str, str] | list[str] | None = None,
        conflicts_with: list[str] | None = None,
        auto_scan: bool = False,
        **_: Any,
    ) -> PluginMetadata | None:
        meta = self.plugins.get(name) or PluginMetadata(name=name)
        meta.version, meta.author, meta.description = str(version), str(author), str(description)
        meta.dependencies = _normalise_deps(dependencies or {})
        meta.conflicts_with = set(conflicts_with or [])
        self.plugins[name] = meta
        if auto_scan and meta.module:
            self.scan_module(meta, meta.module)
        self._schedule_export()
        return meta

    def register_extension(self, name: str, module_name: str, load_time_ms: float = 0.0) -> PluginMetadata:
        meta = PluginMetadata(name=name, module=module_name, load_time_ms=round(load_time_ms, 2))
        self.scan_module(meta, module_name)
        self.plugins[name] = meta
        self._schedule_export()
        return meta

    def scan_module(self, meta: PluginMetadata, module_name: str) -> None:
        module = self.bot.extensions.get(module_name)
        if module is None:
            meta.scan_errors.append(f"module {module_name} not loaded")
            return
        meta.apply({k: getattr(module, k) for k in _DUNDERS if hasattr(module, k)})
        meta.file_path = getattr(module, "__file__", None)
        for cog_name, cog in self.bot.cogs.items():
            if type(cog).__module__ == module_name or type(cog).__module__.startswith(module_name + "."):
                meta.cogs.add(cog_name)
                meta.commands.update(c.qualified_name for c in cog.walk_commands())
                meta.commands.update(c.qualified_name for c in cog.walk_app_commands())

    def unregister_plugin(self, name: str) -> bool:
        removed = self.plugins.pop(name, None) is not None
        if removed:
            self._schedule_export()
        return removed
