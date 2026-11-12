# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .actions import REGISTRY, Action, ActionContext, ActionError
from .capabilities import NAMES

__all__ = ["Panel", "PanelError", "panels"]

PanelHandler = Callable[[ActionContext], Awaitable[Any]]
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
BLOCKS = ("stats", "table", "text", "form", "buttons", "list")
FIELD_KINDS = ("text", "textarea", "number", "bool", "choice")
STYLES = ("primary", "secondary", "danger")


class PanelError(ValueError):
    pass


@dataclass
class Panel:
    id: str
    title: str
    render: PanelHandler
    description: str = ""
    capability: str = "view"
    actions: dict[str, PanelHandler] = field(default_factory=dict)
    action_capability: str = "extensions"
    module: str = ""


def _text(value: Any, limit: int = 500) -> str:
    return str(value if value is not None else "")[:limit]


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    return _text(value, 300)


def clean_blocks(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ActionError("The panel returned something the dashboard cannot show.")
    out: list[dict[str, Any]] = []
    for block in raw[:30]:
        if not isinstance(block, dict) or block.get("type") not in BLOCKS:
            continue
        kind = block["type"]
        title = _text(block.get("title"), 120) or None
        if kind == "stats":
            items = [{"label": _text(i.get("label"), 60), "value": _cell(i.get("value")),
                      "hint": _text(i.get("hint"), 120) or None}
                     for i in block.get("items", [])[:12] if isinstance(i, dict)]
            out.append({"type": kind, "title": title, "items": items})
        elif kind == "table":
            columns = [_text(c, 60) for c in block.get("columns", [])[:12]]
            rows = [[_cell(v) for v in r[:len(columns)]] for r in block.get("rows", [])[:500] if isinstance(r, list)]
            out.append({"type": kind, "title": title, "columns": columns, "rows": rows})
        elif kind == "text":
            out.append({"type": kind, "title": title, "text": _text(block.get("text"), 4000)})
        elif kind == "list":
            out.append({"type": kind, "title": title,
                        "items": [_text(i, 300) for i in block.get("items", [])[:100]]})
        elif kind == "form":
            fields = []
            for f in block.get("fields", [])[:20]:
                if not isinstance(f, dict) or f.get("kind", "text") not in FIELD_KINDS:
                    continue
                fields.append({"key": _text(f.get("key"), 40), "label": _text(f.get("label"), 80),
                               "kind": f.get("kind", "text"), "value": _cell(f.get("value")),
                               "choices": [_text(c, 80) for c in f.get("choices", [])[:50]],
                               "required": bool(f.get("required"))})
            out.append({"type": kind, "title": title, "action": _text(block.get("action"), 40),
                        "submit": _text(block.get("submit") or "Save", 40), "fields": fields})
        elif kind == "buttons":
            buttons = [{"action": _text(b.get("action"), 40), "label": _text(b.get("label"), 40),
                        "style": b.get("style") if b.get("style") in STYLES else "secondary",
                        "confirm": _text(b.get("confirm"), 200) or None}
                       for b in block.get("buttons", [])[:10] if isinstance(b, dict)]
            out.append({"type": kind, "title": title, "buttons": buttons})
    return out


class PanelRegistry:
    def __init__(self) -> None:
        self.panels: dict[str, Panel] = {}

    def register(self, panel: Panel) -> Panel:
        if not _ID.match(panel.id):
            raise PanelError("panel ids use 2-40 lowercase letters, digits, - and _")
        for cap in (panel.capability, panel.action_capability):
            if cap not in NAMES:
                raise PanelError(f"unknown capability {cap!r}")
        for name in panel.actions:
            if not _ID.match(name):
                raise PanelError(f"action names use 2-40 lowercase letters, digits, - and _ ({name!r})")
        self.unregister(panel.id)
        panel.module = panel.module or getattr(panel.render, "__module__", "")

        async def render(ctx: ActionContext) -> dict[str, Any]:
            return {"id": panel.id, "title": panel.title, "blocks": clean_blocks(await panel.render(ctx))}

        REGISTRY[f"panel.{panel.id}"] = Action(f"panel.{panel.id}", panel.capability, render, 30.0)
        for name, handler in panel.actions.items():
            REGISTRY[f"panel.{panel.id}.{name}"] = Action(
                f"panel.{panel.id}.{name}", panel.action_capability, _wrap(panel, handler), 60.0,
                lambda a, n=name: f"{panel.title}: {n}")
        self.panels[panel.id] = panel
        return panel

    def unregister(self, panel_id: str) -> bool:
        panel = self.panels.pop(panel_id, None)
        if panel is None:
            return False
        for key in [k for k in REGISTRY if k == f"panel.{panel_id}" or k.startswith(f"panel.{panel_id}.")]:
            REGISTRY.pop(key, None)
        return True

    def unregister_module(self, module: str) -> int:
        gone = [p.id for p in self.panels.values() if p.module == module or p.module.startswith(f"{module}.")]
        for panel_id in gone:
            self.unregister(panel_id)
        return len(gone)

    def describe(self) -> list[dict[str, Any]]:
        return [{"id": p.id, "title": p.title, "description": p.description, "capability": p.capability,
                 "module": p.module} for p in sorted(self.panels.values(), key=lambda p: p.title.lower())]


def _wrap(panel: Panel, handler: PanelHandler) -> PanelHandler:
    async def run(ctx: ActionContext) -> dict[str, Any]:
        result = await handler(ctx)
        message = result if isinstance(result, str) else (result or {}).get("message") if isinstance(result, dict) else None
        return {"message": _text(message, 500) or None,
                "blocks": clean_blocks(await panel.render(ctx))}

    return run


panels = PanelRegistry()
