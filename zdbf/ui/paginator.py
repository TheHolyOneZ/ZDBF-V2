# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import discord
from discord import ui

from . import cards
from .base import BaseView, button, row
from .theme import Glyph

__all__ = ["PAGE_CHARS", "Paginator", "SelectPager", "chunk_lines", "chunk_text", "nav_row"]

PAGE_CHARS = 3000


def chunk_lines(lines: Sequence[str], per_page: int = 10, *, max_chars: int = PAGE_CHARS) -> list[str]:
    pages: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        line = cards.truncate(line, max_chars)
        if current and (len(current) >= per_page or size + len(line) + 1 > max_chars):
            pages.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        pages.append("\n".join(current))
    return pages or ["*Nothing to show.*"]


def chunk_text(text: str, *, max_chars: int = PAGE_CHARS) -> list[str]:
    pages: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        pieces = [para] if len(para) <= max_chars else _split_long(para, max_chars)
        for piece in pieces:
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) > max_chars and current:
                pages.append(current)
                current = piece
            else:
                current = candidate
    if current:
        pages.append(current)
    return pages or ["*Nothing to show.*"]


def _split_long(para: str, max_chars: int) -> list[str]:
    out, current = [], ""
    for line in para.split("\n"):
        while len(line) > max_chars:
            out.append(line[:max_chars])
            line = line[max_chars:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_chars:
            out.append(current)
            current = line
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def nav_row(index: int, count: int, goto: Callable[[discord.Interaction[Any], int], Awaitable[None]]) -> ui.ActionRow[Any]:
    last = count - 1

    def to(target: Callable[[], int]):
        async def cb(interaction: discord.Interaction[Any]) -> None:
            await goto(interaction, max(0, min(target(), last)))

        return cb

    return row(
        button(Glyph.FIRST, to(lambda: 0), disabled=index == 0),
        button(Glyph.PREV, to(lambda: (index - 1) % count)),
        button(f"{index + 1} / {count}", disabled=True),
        button(Glyph.NEXT, to(lambda: (index + 1) % count)),
        button(Glyph.LAST, to(lambda: last), disabled=index == last),
    )


class Paginator(BaseView):
    def __init__(
        self,
        pages: Sequence[str | Sequence[Any]],
        *,
        title: str,
        emoji: str | None = None,
        subtitle: str | None = None,
        accent: str | discord.Colour | None = "primary",
        foot: str | None = None,
        thumbnail: str | None = None,
        start: int = 0,
        links: Sequence[ui.Button[Any]] = (),
        author_id: int | None = None,
        timeout: float | None = 300,
    ) -> None:
        super().__init__(author_id=author_id, timeout=timeout)
        self.pages = list(pages) or ["*Nothing to show.*"]
        self.title = title
        self.emoji = emoji
        self.subtitle = subtitle
        self.accent = accent
        self.foot = foot
        self.thumbnail = thumbnail
        self.links = list(links)
        self.index = max(0, min(start, len(self.pages) - 1))

    @classmethod
    def from_lines(cls, lines: Sequence[str], *, per_page: int = 10, **kwargs: Any) -> Paginator:
        return cls(chunk_lines(lines, per_page), **kwargs)

    @classmethod
    def from_text(cls, text: str, *, max_chars: int = PAGE_CHARS, **kwargs: Any) -> Paginator:
        return cls(chunk_text(text, max_chars=max_chars), **kwargs)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def extra_items(self) -> list[ui.Item[Any]]:
        return []

    async def _goto(self, interaction: discord.Interaction[Any], index: int) -> None:
        self.index = index
        await self.refresh(interaction)

    def build(self) -> None:
        self.clear_items()
        page = self.pages[self.index]
        body = [page] if isinstance(page, str) else list(page)
        foot = f"Page {self.index + 1} of {self.page_count}" if self.page_count > 1 else None
        if self.foot:
            foot = f"{self.foot} · {foot}" if foot else self.foot
        box = cards.card(self.title, *body, subtitle=self.subtitle, emoji=self.emoji, accent=self.accent,
                         thumbnail=self.thumbnail, foot=foot)
        if self.page_count > 1:
            box.add_item(nav_row(self.index, self.page_count, self._goto))
        for item in self.extra_items():
            box.add_item(item)
        if self.links:
            box.add_item(row(*self.links))
        self.add_item(box)


class SelectPager:
    PER_PAGE = 25

    def __init__(self, options: Sequence[discord.SelectOption],
                 on_pick: Callable[[discord.Interaction[Any], list[str]], Awaitable[None]], *,
                 placeholder: str = "Select…", max_values: int = 1) -> None:
        self.options = list(options)
        self.on_pick = on_pick
        self.placeholder = placeholder
        self.max_values = max_values
        self.page = 0

    def set_options(self, options: Sequence[discord.SelectOption]) -> None:
        self.options = list(options)
        self.page = min(self.page, max(0, self.pages - 1))

    @property
    def pages(self) -> int:
        return max(1, (len(self.options) + self.PER_PAGE - 1) // self.PER_PAGE)

    def rows(self, view: BaseView) -> list[ui.ActionRow[Any]]:
        if not self.options:
            return []
        start = self.page * self.PER_PAGE
        chunk = self.options[start:start + self.PER_PAGE]
        placeholder = self.placeholder if self.pages == 1 else f"{self.placeholder} ({self.page + 1}/{self.pages})"
        sel: ui.Select[Any] = ui.Select(options=chunk, placeholder=placeholder[:150],
                                        min_values=1, max_values=min(self.max_values, len(chunk)))

        async def picked(interaction: discord.Interaction[Any]) -> None:
            await self.on_pick(interaction, list(sel.values))

        sel.callback = picked  # type: ignore[method-assign]
        out = [row(sel)]
        if self.pages > 1:
            async def prev(interaction: discord.Interaction[Any]) -> None:
                self.page = (self.page - 1) % self.pages
                await view.refresh(interaction)

            async def nxt(interaction: discord.Interaction[Any]) -> None:
                self.page = (self.page + 1) % self.pages
                await view.refresh(interaction)

            out.append(row(button(f"{Glyph.PREV} Previous options", prev), button(f"More options {Glyph.NEXT}", nxt)))
        return out
