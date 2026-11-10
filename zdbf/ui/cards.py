# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import discord
from discord import ui

from .theme import accent_for, emoji_for

__all__ = [
    "MAX_COMPONENTS",
    "MAX_TEXT",
    "alert_view",
    "bar",
    "card",
    "codeblock",
    "container",
    "error",
    "fields",
    "fits",
    "footer",
    "header",
    "info",
    "kv",
    "section",
    "sep",
    "set_decorative_emoji",
    "static",
    "success",
    "text",
    "timestamp",
    "truncate",
    "warning",
]

MAX_TEXT = 4000
MAX_COMPONENTS = 40
BRAND = "ZDBF"

Child = ui.Item[Any] | str | None

_decorative = False


def set_decorative_emoji(enabled: bool) -> None:
    global _decorative
    _decorative = enabled


def truncate(value: Any, limit: int = MAX_TEXT, suffix: str = "…") -> str:
    s = str(value)
    return s if len(s) <= limit else s[: max(0, limit - len(suffix))] + suffix


def text(content: Any) -> ui.TextDisplay[Any]:
    return ui.TextDisplay(truncate(content))


def sep(*, large: bool = False, visible: bool = True) -> ui.Separator[Any]:
    spacing = discord.SeparatorSpacing.large if large else discord.SeparatorSpacing.small
    return ui.Separator(visible=visible, spacing=spacing)


def header(title: str, subtitle: str | None = None, *, emoji: str | None = None, level: int = 2) -> str:
    hashes = "#" * max(1, min(level, 3))
    mark = f"{emoji} " if emoji and _decorative else ""
    line = f"{hashes} {mark}{title}"
    return f"{line}\n-# {subtitle}" if subtitle else line


def footer(content: str, *, with_time: bool = False, brand: bool = True) -> ui.TextDisplay[Any]:
    parts = [BRAND] if brand and not content.startswith(BRAND) else []
    parts.append(content)
    if with_time:
        parts.append(timestamp())
    return ui.TextDisplay(truncate("-# " + " · ".join(p for p in parts if p)))


def timestamp(when: dt.datetime | float | str | None = None, style: str = "R") -> str:
    if when is None:
        when = dt.datetime.now(dt.UTC)
    if isinstance(when, str):
        try:
            parsed = dt.datetime.fromisoformat(when)
        except ValueError:
            return when
        when = parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    ts = int(when.timestamp() if isinstance(when, dt.datetime) else when)
    return f"<t:{ts}:{style}>"


def codeblock(content: Any, lang: str = "") -> str:
    body = str(content).replace("```", "`​``")
    return f"```{lang}\n{truncate(body, MAX_TEXT - 12)}\n```"


def kv(pairs: Mapping[str, Any] | Iterable[tuple[str, Any]], *, code: bool = False, sep_: str = "  ") -> str:
    items = list(pairs.items() if isinstance(pairs, Mapping) else pairs)
    if code:
        return "\n".join(f"**{k}**{sep_}`{v}`" for k, v in items)
    return "\n".join(f"**{k}**{sep_}{v}" for k, v in items)


def fields(pairs: Mapping[str, Any] | Iterable[tuple[str, Any]]) -> str:
    items = pairs.items() if isinstance(pairs, Mapping) else pairs
    return "\n\n".join(f"**{k}**\n{v}" for k, v in items)


def bar(value: float, maximum: float = 100, width: int = 14) -> str:
    ratio = 0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
    filled = round(ratio * width)
    return f"`{'▰' * filled}{'▱' * (width - filled)}`  {ratio * 100:.0f}%"


def _coerce(children: Iterable[Child]) -> list[ui.Item[Any]]:
    out: list[ui.Item[Any]] = []
    for child in children:
        if child is None or child == "":
            continue
        out.append(text(child) if isinstance(child, str) else child)
    return out


def section(content: str | Sequence[str], accessory: ui.Item[Any]) -> ui.Section[Any]:
    blocks = [content] if isinstance(content, str) else list(content)[:3]
    return ui.Section(*[truncate(b) for b in blocks], accessory=accessory)


def container(*children: Child, accent: str | discord.Colour | int | None = None) -> ui.Container[Any]:
    colour = accent_for(accent) if isinstance(accent, str) else accent
    return ui.Container(*_coerce(children), accent_colour=colour)


def card(
    title: str | None,
    *body: Child,
    subtitle: str | None = None,
    emoji: str | None = None,
    accent: str | discord.Colour | int | None = "primary",
    thumbnail: str | None = None,
    foot: str | None = None,
) -> ui.Container[Any]:
    children: list[Child] = []
    if title:
        head = header(title, subtitle, emoji=emoji)
        children.append(section(head, ui.Thumbnail(thumbnail)) if thumbnail else head)
        if body:
            children.append(sep())
    children.extend(body)
    if foot:
        children.append(sep(visible=False))
        children.append(footer(foot))
    return container(*children, accent=accent)


class StaticView(ui.LayoutView):
    def __init__(self, *items: ui.Item[Any]) -> None:
        super().__init__(timeout=None)
        for item in items:
            self.add_item(item)


def fits(view: ui.LayoutView) -> bool:
    return view.content_length() <= MAX_TEXT and view.total_children_count <= MAX_COMPONENTS


def _walk(items: Any) -> Any:
    for item in items:
        yield item
        if hasattr(item, "walk_children"):
            yield from item.walk_children()


def _split_oversized(items: Any) -> ui.LayoutView:
    from .paginator import Paginator, chunk_text

    texts: list[str] = []
    links: list[ui.Button[Any]] = []
    accent: Any = None
    for item in _walk(items):
        if isinstance(item, ui.Container) and accent is None:
            accent = item.accent_colour
        elif isinstance(item, ui.TextDisplay):
            texts.append(item.content)
        elif isinstance(item, ui.Button) and item.url and len(links) < 5:
            links.append(item)
    title = "Details"
    if texts and texts[0].startswith("#"):
        first = texts.pop(0).split("\n")
        title = first[0].lstrip("# ").strip() or title
    foot = next((t[3:] for t in reversed(texts) if t.startswith("-# ")), None)
    if foot is not None:
        texts.remove(f"-# {foot}")
    pages = chunk_text("\n\n".join(texts), max_chars=3200)
    links = [ui.Button(label=b.label, url=b.url, emoji=b.emoji) for b in links]
    pager = Paginator(pages, title=title, accent=accent, foot=foot, links=links)
    pager.build()
    return pager


def static(*items: ui.Item[Any] | str) -> ui.LayoutView:
    coerced = _coerce(items)
    try:
        view = StaticView(*coerced)
    except ValueError:
        return _split_oversized(coerced)
    return view if fits(view) else _split_oversized(view.children)


def _level_view(level: str, title: str, message: str | None, **kw: Any) -> ui.LayoutView:
    kw.setdefault("accent", level)
    return static(card(title, message, **kw))


def success(title: str, message: str | None = None, **kw: Any) -> ui.LayoutView:
    return _level_view("success", title, message, **kw)


def info(title: str, message: str | None = None, **kw: Any) -> ui.LayoutView:
    return _level_view("info", title, message, **kw)


def warning(title: str, message: str | None = None, **kw: Any) -> ui.LayoutView:
    return _level_view("warning", title, message, **kw)


def error(title: str, message: str | None = None, **kw: Any) -> ui.LayoutView:
    return _level_view("error", title, message, **kw)


def alert_view(system: str, message: str, level: str = "warning", *, title: str | None = None) -> ui.LayoutView:
    dot = emoji_for(level)
    return static(card(
        f"{dot} {title or f'{system.title()} alert'}".strip(),
        message,
        accent=level,
        foot=f"{system} · {timestamp(style='f')}",
    ))
