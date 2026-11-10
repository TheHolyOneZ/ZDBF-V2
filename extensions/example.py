# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from zdbf.ui import BaseView, button, cards, row

__version__ = "2.0.0"
__author__ = "TheHolyOneZ"
__description__ = "Example extension: cards, an interactive counter and event hooks"
__dependencies__: list[str] = []
__conflicts__: list[str] = []
__listens_to_hooks__ = ["command_executed"]

log = logging.getLogger("extensions.example")


class CounterView(BaseView):
    def __init__(self, bot: Any, guild_id: int, count: int, author_id: int) -> None:
        super().__init__(author_id=author_id)
        self.bot = bot
        self.guild_id = guild_id
        self.count = count

    def build(self) -> None:
        self.clear_items()
        box = cards.card("Counter", f"This server pressed the button **{self.count:,}** times.", emoji="🔢")

        async def plus(interaction: discord.Interaction[Any]) -> None:
            self.count += 1
            await self.bot.db.set_setting(self.guild_id, "example.counter", self.count)
            await self.refresh(interaction)

        box.add_item(row(button("+1", plus, emoji="➕", style=discord.ButtonStyle.success)))
        self.add_item(box)


class Example(commands.Cog, name="Example"):
    """A small demo of the ZDBF V2 extension API."""

    emoji = "🧪"

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.register_hook("command_executed", self.on_command_used)

    async def on_command_used(self, bot: Any, command_name: str, author: Any, guild: Any, **_: Any) -> None:
        log.debug("command %s used by %s in %s", command_name, author, guild)

    @commands.hybrid_group(name="example", description="Example extension", invoke_without_command=True)
    async def example(self, ctx: commands.Context[Any]) -> None:
        await self.example_card.callback(self, ctx)  # type: ignore[arg-type]

    @example.command(name="card", description="Show a Components V2 card")
    async def example_card(self, ctx: commands.Context[Any]) -> None:
        await ctx.send(view=cards.static(cards.card(
            "Hello from an extension!",
            cards.kv({"Server": ctx.guild.name if ctx.guild else "DM", "You": ctx.author.mention}),
            cards.sep(),
            "Edit `extensions/example.py` and save - hot reload picks it up within seconds.",
            emoji="👋", accent="brand", foot="ZDBF V2 example extension")))

    @example.command(name="counter", description="An interactive, persistent counter")
    @commands.guild_only()
    async def example_counter(self, ctx: commands.Context[Any]) -> None:
        assert ctx.guild is not None
        count = await self.bot.db.get_setting(ctx.guild.id, "example.counter", 0)
        await CounterView(self.bot, ctx.guild.id, count, ctx.author.id).send(ctx)


async def setup(bot: Any) -> None:
    await bot.add_cog(Example(bot))
