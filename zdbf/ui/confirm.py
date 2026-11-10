# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import discord
from discord import ui

from . import cards
from .base import BaseView, Target, button, row

__all__ = ["ConfirmView", "FormField", "FormModal", "confirm"]


class ConfirmView(BaseView):
    def __init__(
        self,
        title: str,
        message: str,
        *,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        danger: bool = True,
        author_id: int | None = None,
        timeout: float = 60,
    ) -> None:
        super().__init__(author_id=author_id, timeout=timeout)
        self.title = title
        self.body = message
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label
        self.danger = danger
        self.value: bool | None = None
        self.interaction: discord.Interaction[Any] | None = None
        self._result: str | None = None

    def build(self) -> None:
        self.clear_items()
        if self._result is not None:
            accent = "success" if self.value else "muted"
            self.add_item(cards.card(self.title, self._result, accent=accent))
            return
        box = cards.card(self.title, self.body,
                         accent="warning" if self.danger else "primary")
        box.add_item(
            row(
                button(
                    self.confirm_label,
                    self._yes,
                    style=discord.ButtonStyle.danger if self.danger else discord.ButtonStyle.success,
                ),
                button(self.cancel_label, self._no),
            )
        )
        self.add_item(box)

    async def _finish(self, interaction: discord.Interaction[Any], value: bool) -> None:
        self.value = value
        self.interaction = interaction
        self._result = "Confirmed - working on it…" if value else "Cancelled."
        await self.refresh(interaction)
        self.stop()

    async def _yes(self, interaction: discord.Interaction[Any]) -> None:
        await self._finish(interaction, True)

    async def _no(self, interaction: discord.Interaction[Any]) -> None:
        await self._finish(interaction, False)

    async def on_timeout(self) -> None:
        self._result = "Timed out - nothing was changed."
        self.build()
        await super().on_timeout()


async def confirm(target: Target, title: str, message: str, *, ephemeral: bool = False, **kw: Any) -> ConfirmView:
    view = ConfirmView(title, message, **kw)
    await view.send(target, ephemeral=ephemeral)
    await view.wait()
    return view


@dataclass
class FormField:
    key: str
    label: str
    description: str | None = None
    placeholder: str | None = None
    default: str | None = None
    required: bool = True
    paragraph: bool = False
    min_length: int | None = None
    max_length: int | None = None


class FormModal(ui.Modal):
    def __init__(
        self,
        title: str,
        form: list[FormField],
        on_done: Callable[[discord.Interaction[Any], dict[str, str]], Awaitable[Any]],
        *,
        timeout: float | None = 600,
    ) -> None:
        super().__init__(title=cards.truncate(title, 45), timeout=timeout)
        self._on_done = on_done
        self._inputs: dict[str, ui.TextInput[Any]] = {}
        for f in form[:5]:
            field_input: ui.TextInput[Any] = ui.TextInput(
                style=discord.TextStyle.paragraph if f.paragraph else discord.TextStyle.short,
                placeholder=f.placeholder,
                default=f.default,
                required=f.required,
                min_length=f.min_length,
                max_length=f.max_length,
            )
            self._inputs[f.key] = field_input
            self.add_item(ui.Label(text=cards.truncate(f.label, 45), description=f.description, component=field_input))

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        await self._on_done(interaction, {k: v.value.strip() for k, v in self._inputs.items()})

    async def on_error(self, interaction: discord.Interaction[Any], error: Exception) -> None:
        view = cards.error("Could not process the form", f"{type(error).__name__}: {cards.truncate(error, 300)}")
        if interaction.response.is_done():
            await interaction.followup.send(view=view, ephemeral=True)
        else:
            await interaction.response.send_message(view=view, ephemeral=True)
