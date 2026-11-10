# ZSync Marketplace client - Copyright (c) 2025-2026 TheHolyOneZ (TheZ). All rights reserved.
# Licensed under the ZSync Marketplace License (LICENSE-MARKETPLACE), NOT the Apache License.
# The names ZSync, ZDBF, Zoryx, TheHolyOneZ and TheZ must not be removed or altered.
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import ui

from ..ui import (
    BaseView,
    FormField,
    FormModal,
    Glyph,
    Status,
    button,
    cards,
    chunk_text,
    link_button,
    nav_row,
    row,
    select,
)
from .client import Extension

if TYPE_CHECKING:
    from .cog import Marketplace

MARKETPLACE_URL = "https://zsync.eu/extension/"
PER_PAGE = 4
LICENSE_TERMS = (
    "**1.** Downloaded extensions may **only** be used within the **ZSync ecosystem** (including **ZDBF / Zoryx**).",
    "**2.** You must **not** remove, alter or obscure the names **ZSync**, **ZDBF**, **Zoryx**, **TheHolyOneZ**, **TheZ**.",
    "**3.** Every extension has its **own license** at the top of its file - respect those terms.",
    "**4.** Extensions must **not** be redistributed outside authorized ZSync systems.",
    "**5.** Violations lead to **ZSync ZDBF Key deactivation** and a ban from all ZSync services.",
)


class LicenseView(BaseView):
    def __init__(self, author_id: int) -> None:
        super().__init__(author_id=author_id, timeout=180)
        self.accepted: bool | None = None

    def build(self) -> None:
        self.clear_items()
        if self.accepted is not None:
            self.add_item(cards.card("License " + ("accepted" if self.accepted else "declined"),
                                     "Welcome to the ZSync Marketplace." if self.accepted else
                                     "You need to accept the license to use the marketplace.",
                                     accent="success" if self.accepted else "muted"))
            return
        box = cards.card(
            "ZSync Marketplace License",
            "**Please read and accept these terms to use the marketplace:**",
            cards.sep(),
            "\n".join(LICENSE_TERMS),
            cards.sep(),
            "-# Full text: `LICENSE-MARKETPLACE` · Copyright © 2025-2026 TheHolyOneZ (TheZ)", accent="gold",
        )

        async def accept(interaction: discord.Interaction[Any]) -> None:
            self.accepted = True
            await self.refresh(interaction)
            self.stop()

        async def decline(interaction: discord.Interaction[Any]) -> None:
            self.accepted = False
            await self.refresh(interaction)
            self.stop()

        box.add_item(row(button("Accept", accept, style=discord.ButtonStyle.success),
                         button("Decline", decline, style=discord.ButtonStyle.danger)))
        self.add_item(box)


def detail_pages(ext: Extension) -> list[str]:
    text = ext.details or "*No further details.*"
    if ext.changelog:
        text += f"\n\n**Changelog**\n{ext.changelog}"
    return chunk_text(text, max_chars=1800)


def detail_card(ext: Extension, installed: dict[str, Any] | None, page: int = 0) -> ui.Container[Any]:
    state = "not installed"
    if installed:
        state = f"installed v{installed.get('version')}"
        if installed.get("version") != ext.version:
            state += f" · **update available: v{ext.version}**"
    pages = detail_pages(ext)
    page = max(0, min(page, len(pages) - 1))
    return cards.card(
        ext.title,
        ext.description or "*No description.*",
        cards.sep(),
        cards.kv({"Version": ext.version, "Creator": ext.creator + (" · official" if ext.official else ""),
                  "Status": f"{ext.status_emoji} {ext.status}", "Released": ext.released.strftime("%Y-%m-%d")
                  if ext.released else "-", "File": f"`{ext.filename}`", "ID": ext.id, "Installed": state}),
        cards.sep(),
        pages[page],
        subtitle="ZSync Marketplace extension",
        accent="success" if ext.status == "working" else "warning",
        foot=f"Details page {page + 1} of {len(pages)}" if len(pages) > 1 else None,
    )


class MarketplaceView(BaseView):
    def __init__(self, cog: Marketplace, items: list[Extension], author_id: int, *, title: str = "ZSync Marketplace",
                 query: str | None = None) -> None:
        super().__init__(author_id=author_id, timeout=900)
        self.cog = cog
        self.all = items
        self.title = title
        self.query = query
        self.filter = "all"
        self.sort = "newest"
        self.page = 0
        self.detail_page = 0
        self.selected: Extension | None = None

    @property
    def items(self) -> list[Extension]:
        items = self.all
        match self.filter:
            case "official":
                items = [e for e in items if e.official]
            case "community":
                items = [e for e in items if not e.official]
            case "installed":
                items = [e for e in items if e.filename in self.cog.installed]
            case "all":
                pass
            case status:
                items = [e for e in items if e.status == status]
        if self.sort == "name":
            return sorted(items, key=lambda e: e.title.lower())
        if self.query:
            return items
        return sorted(items, key=lambda e: (e.date, e.id), reverse=True)

    def build(self) -> None:
        self.clear_items()
        self.add_item(self._detail() if self.selected else self._list())

    def _list(self) -> ui.Container[Any]:
        items = self.items
        pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
        self.page = min(self.page, pages - 1)
        chunk = items[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]
        subtitle = f"{len(items)} extension(s)" + (f" matching “{self.query}”" if self.query else "") + \
                   f" · filter: {self.filter} · sort: {self.sort if not self.query or self.sort == 'name' else 'relevance'}"
        box = cards.card(self.title, subtitle=subtitle, accent="brand")
        for ext in chunk:
            badge = " · *installed*" if ext.filename in self.cog.installed else ""
            box.add_item(cards.section(
                [f"{ext.status_emoji} **{ext.title}** `v{ext.version}` · {ext.creator}{badge}",
                 f"-# {cards.truncate(ext.description, 140)}"],
                self._details_button(ext)))
        if not chunk:
            box.add_item(cards.text("*Nothing found - try another search or filter.*"))
        box.add_item(cards.sep())

        async def set_filter(interaction: discord.Interaction[Any]) -> None:
            self.filter = interaction.data["values"][0]  # type: ignore[index]
            self.page = 0
            await self.refresh(interaction)

        options = [discord.SelectOption(label=label, value=value, emoji=emoji or None, default=self.filter == value)
                   for value, label, emoji in (("all", "All extensions", ""), ("working", "Working", Status.OK),
                                               ("beta", "Beta", Status.WARN), ("broken", "Broken", Status.ERROR),
                                               ("official", "Official (TheHolyOneZ)", ""),
                                               ("community", "Community", ""), ("installed", "Installed", ""))]
        box.add_item(row(select(options, set_filter, placeholder="Filter")))

        async def prev(interaction: discord.Interaction[Any]) -> None:
            self.page = (self.page - 1) % pages
            await self.refresh(interaction)

        async def nxt(interaction: discord.Interaction[Any]) -> None:
            self.page = (self.page + 1) % pages
            await self.refresh(interaction)

        async def sort(interaction: discord.Interaction[Any]) -> None:
            self.sort = "name" if self.sort == "newest" else "newest"
            await self.refresh(interaction)

        async def search(interaction: discord.Interaction[Any]) -> None:
            async def done(modal_inter: discord.Interaction[Any], values: dict[str, str]) -> None:
                self.query = values["q"] or None
                self.all = await self.cog.client.search(values["q"]) if values["q"] else await self.cog.client.list()
                self.page = 0
                await self.refresh(modal_inter)

            await interaction.response.send_modal(FormModal("Search the marketplace", [
                FormField("q", "Search", placeholder="e.g. music, tickets, economy", required=False,
                          default=self.query)], done))

        box.add_item(row(button(Glyph.PREV, prev, disabled=pages == 1),
                         button(f"{self.page + 1} / {pages}", disabled=True),
                         button(Glyph.NEXT, nxt, disabled=pages == 1),
                         button("Sort: " + ("A to Z" if self.sort == "name" else "Newest"), sort),
                         button("Search", search, style=discord.ButtonStyle.primary)))
        box.add_item(cards.footer("ZSync Marketplace · zsync.eu · extensions keep their own licenses", brand=False))
        return box

    def _details_button(self, ext: Extension) -> ui.Button[Any]:
        async def cb(interaction: discord.Interaction[Any]) -> None:
            self.selected = ext
            self.detail_page = 0
            await self.refresh(interaction)

        return button("Details", cb)

    def _detail(self) -> ui.Container[Any]:
        ext = self.selected
        assert ext is not None
        installed = self.cog.installed.get(ext.filename)
        box = detail_card(ext, installed, self.detail_page)
        pages = len(detail_pages(ext))
        if pages > 1:
            async def goto(interaction: discord.Interaction[Any], index: int) -> None:
                self.detail_page = index
                await self.refresh(interaction)

            box.add_item(nav_row(min(self.detail_page, pages - 1), pages, goto))

        async def install(interaction: discord.Interaction[Any]) -> None:
            await self.cog.install_flow(interaction, ext)

        async def back(interaction: discord.Interaction[Any]) -> None:
            self.selected = None
            await self.refresh(interaction)

        label = "Install"
        if installed:
            label = "Update" if installed.get("version") != ext.version else "Reinstall"
        box.add_item(row(button(label, install, style=discord.ButtonStyle.success),
                         button(f"{Glyph.PREV} Back", back),
                         link_button("Open ZSync", MARKETPLACE_URL)))
        return box
