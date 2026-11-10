# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import discord
from discord import ui
from discord.ext import commands

from . import cards

log = logging.getLogger("zdbf.ui")

__all__ = ["BaseView", "button", "link_button", "respond", "row", "select"]

Target = commands.Context[Any] | discord.Interaction[Any]
Callback = Callable[[discord.Interaction[Any]], Awaitable[Any]]


def button(
    label: str | None = None,
    callback: Callback | None = None,
    *,
    style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    emoji: str | None = None,
    disabled: bool = False,
    custom_id: str | None = None,
) -> ui.Button[Any]:
    btn: ui.Button[Any] = ui.Button(label=label, style=style, emoji=emoji or None, disabled=disabled,
                                    custom_id=custom_id)
    if callback is not None:
        btn.callback = callback  # type: ignore[method-assign]
    return btn


def link_button(label: str, url: str, *, emoji: str | None = None) -> ui.Button[Any]:
    return ui.Button(label=label, url=url, emoji=emoji or None, style=discord.ButtonStyle.link)


def select(
    options: list[discord.SelectOption],
    callback: Callback,
    *,
    placeholder: str | None = None,
    min_values: int = 1,
    max_values: int = 1,
    disabled: bool = False,
) -> ui.Select[Any]:
    sel: ui.Select[Any] = ui.Select(
        options=options[:25] or [discord.SelectOption(label="Nothing here", value="__none__")],
        placeholder=placeholder,
        min_values=min_values,
        max_values=max_values,
        disabled=disabled or not options,
    )
    sel.callback = callback  # type: ignore[method-assign]
    return sel


def row(*items: ui.Item[Any] | None) -> ui.ActionRow[Any]:
    return ui.ActionRow(*[i for i in items if i is not None])


async def respond(
    target: Target,
    view: ui.LayoutView,
    *,
    ephemeral: bool = False,
    files: list[discord.File] | None = None,
) -> discord.Message | None:
    allowed = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False)
    kwargs: dict[str, Any] = {"view": view, "allowed_mentions": allowed}
    if files:
        kwargs["files"] = files
    if isinstance(target, commands.Context):
        if target.interaction is None:
            ephemeral = False
        return await target.send(ephemeral=ephemeral, **kwargs)
    if not target.response.is_done():
        await target.response.send_message(ephemeral=ephemeral, **kwargs)
        with contextlib.suppress(discord.HTTPException):
            return await target.original_response()
        return None
    return await target.followup.send(ephemeral=ephemeral, wait=True, **kwargs)


class BaseView(ui.LayoutView):
    def __init__(self, *, author_id: int | None = None, timeout: float | None = 300) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.message: discord.Message | None = None
        self._interaction: discord.Interaction[Any] | None = None

    def build(self) -> None:
        pass

    async def send(self, target: Target, *, ephemeral: bool = False,
                   files: list[discord.File] | None = None) -> discord.Message | None:
        if isinstance(target, commands.Context) and self.author_id is None:
            self.author_id = target.author.id
        elif isinstance(target, discord.Interaction) and self.author_id is None:
            self.author_id = target.user.id
        self.build()
        if isinstance(target, discord.Interaction):
            self._interaction = target
        elif target.interaction is not None:
            self._interaction = target.interaction
        self.message = await respond(target, self, ephemeral=ephemeral, files=files)
        return self.message

    async def refresh(self, interaction: discord.Interaction[Any] | None = None) -> None:
        self.build()
        if interaction is not None and not interaction.response.is_done():
            await interaction.response.edit_message(view=self)
            self._interaction = interaction
            return
        if interaction is not None:
            with contextlib.suppress(discord.HTTPException):
                await interaction.edit_original_response(view=self)
                return
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)

    async def interaction_check(self, interaction: discord.Interaction[Any]) -> bool:
        if self.author_id is None or interaction.user.id == self.author_id:
            return True
        client = interaction.client
        if isinstance(client, commands.Bot) and await client.is_owner(interaction.user):
            return True
        await interaction.response.send_message(
            view=cards.error("Not your menu", "Run the command yourself to get your own menu."), ephemeral=True
        )
        return False

    def disable_all(self) -> None:
        for item in self.walk_children():
            if isinstance(item, (ui.Button, ui.Select)) and not (
                isinstance(item, ui.Button) and item.style is discord.ButtonStyle.link
            ):
                item.disabled = True

    async def on_timeout(self) -> None:
        self.disable_all()
        target = self.message
        try:
            if target is not None:
                await target.edit(view=self)
            elif self._interaction is not None:
                await self._interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass

    async def on_error(self, interaction: discord.Interaction[Any], error: Exception, item: ui.Item[Any]) -> None:
        log.exception("error in view %s (item %r)", type(self).__name__, item, exc_info=error)
        view = cards.error("Something went wrong", f"{type(error).__name__}: {cards.truncate(error, 300)}")
        with contextlib.suppress(discord.HTTPException):
            if interaction.response.is_done():
                await interaction.followup.send(view=view, ephemeral=True)
            else:
                await interaction.response.send_message(view=view, ephemeral=True)
