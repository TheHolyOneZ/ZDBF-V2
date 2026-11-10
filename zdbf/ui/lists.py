# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import discord
from discord import ui

from . import cards
from .base import BaseView, button, row
from .paginator import SelectPager, nav_row
from .theme import Glyph

__all__ = ["ListDetailView"]


class ListDetailView[T](BaseView):
    per_page = 6
    title = "Items"
    accent: Any = "primary"
    placeholder = "Open an item…"
    empty_text = "*Nothing here yet.*"

    def __init__(self, items: Sequence[T], *, author_id: int | None = None, timeout: float | None = 600) -> None:
        super().__init__(author_id=author_id, timeout=timeout)
        self.items: list[T] = list(items)
        self.page = 0
        self.selected: T | None = None
        self.note: str | None = None
        self.picker = SelectPager([], self._picked, placeholder=self.placeholder)

    def item_line(self, item: T) -> str:
        raise NotImplementedError

    def item_key(self, item: T) -> str:
        raise NotImplementedError

    def item_option(self, item: T) -> discord.SelectOption:
        return discord.SelectOption(label=cards.truncate(self.item_key(item), 100), value=self.item_key(item))

    def detail(self, item: T) -> ui.Container[Any]:
        raise NotImplementedError

    def subtitle(self) -> str | None:
        return None

    def intro(self) -> list[Any]:
        return []

    def list_controls(self) -> list[ui.Item[Any]]:
        return []

    def detail_controls(self, item: T) -> list[ui.Item[Any]]:
        return []

    def foot(self) -> str | None:
        return None

    def select(self, key: str | None) -> None:
        self.selected = next((i for i in self.items if self.item_key(i) == key), None) if key else None

    def replace_items(self, items: Sequence[T]) -> None:
        key = self.item_key(self.selected) if self.selected is not None else None
        self.items = list(items)
        self.select(key)

    async def _picked(self, interaction: discord.Interaction[Any], values: list[str]) -> None:
        self.select(values[0])
        self.note = None
        await self.refresh(interaction)

    async def _goto(self, interaction: discord.Interaction[Any], index: int) -> None:
        self.page = index
        await self.refresh(interaction)

    async def _back(self, interaction: discord.Interaction[Any]) -> None:
        self.selected = None
        self.note = None
        await self.refresh(interaction)

    @property
    def page_count(self) -> int:
        return max(1, (len(self.items) + self.per_page - 1) // self.per_page)

    def build(self) -> None:
        self.clear_items()
        if self.selected is not None:
            box = self.detail(self.selected)
            if self.note:
                box.add_item(cards.text(self.note))
            controls = self.detail_controls(self.selected)
            back = button(f"{Glyph.PREV} Back", self._back)
            if len(controls) <= 4:
                box.add_item(row(*controls, back))
            else:
                for i in range(0, len(controls), 5):
                    box.add_item(row(*controls[i:i + 5]))
                box.add_item(row(back))
            self.add_item(box)
            return
        self.page = min(self.page, self.page_count - 1)
        chunk = self.items[self.page * self.per_page:(self.page + 1) * self.per_page]
        lines = "\n".join(self.item_line(i) for i in chunk) or self.empty_text
        foot = self.foot()
        if self.page_count > 1:
            foot = f"{foot} · Page {self.page + 1} of {self.page_count}" if foot else \
                f"Page {self.page + 1} of {self.page_count}"
        box = cards.card(self.title, *self.intro(), lines, subtitle=self.subtitle(), accent=self.accent, foot=foot)
        if self.note:
            box.add_item(cards.text(self.note))
        if self.page_count > 1:
            box.add_item(nav_row(self.page, self.page_count, self._goto))
        self.picker.set_options([self.item_option(i) for i in self.items])
        for r in self.picker.rows(self):
            box.add_item(r)
        for item in self.list_controls():
            box.add_item(item)
        self.add_item(box)
