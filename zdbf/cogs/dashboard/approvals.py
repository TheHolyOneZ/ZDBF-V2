# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any

import discord
from discord import ui

from ...ui import button, cards, row

if TYPE_CHECKING:
    from ...core.bot import ZDBFBot

__all__ = ["ApprovalManager"]

log = logging.getLogger("zdbf.dashboard.approvals")
GRANT_SECONDS = 900


class _Decision:
    def __init__(self) -> None:
        self.future: asyncio.Future[tuple[bool, bool, str]] = asyncio.get_running_loop().create_future()

    def settle(self, approved: bool, grant: bool, who: str) -> bool:
        if self.future.done():
            return False
        self.future.set_result((approved, grant, who))
        return True


class _ApprovalView(ui.LayoutView):
    def __init__(self, bot: ZDBFBot, decision: _Decision, title: str, lines: list[str], timeout: float) -> None:
        super().__init__(timeout=timeout + 5)
        self.bot = bot
        self.decision = decision
        self.title = title
        self.lines = lines
        self.message: discord.Message | None = None
        self.render(None)

    def render(self, outcome: str | None) -> None:
        self.clear_items()
        accent = "warning" if outcome is None else "success" if outcome.startswith("Approved") else "muted"
        box = cards.card(self.title, "\n".join(self.lines), outcome, accent=accent,
                         foot="ZDBF Dashboard · the action only runs if you approve it")
        if outcome is None:
            box.add_item(row(
                button("Approve", self._handler(True, False), style=discord.ButtonStyle.success),
                button("Approve for 15 minutes", self._handler(True, True)),
                button("Deny", self._handler(False, False), style=discord.ButtonStyle.danger),
            ))
        self.add_item(box)

    def _handler(self, approved: bool, grant: bool) -> Any:
        async def callback(interaction: discord.Interaction[Any]) -> None:
            if not await self.bot.is_owner(interaction.user):
                await interaction.response.send_message(
                    view=cards.error("Owner only", "Only the bot owner can answer this request."), ephemeral=True)
                return
            if not self.decision.settle(approved, grant, str(interaction.user)):
                await interaction.response.send_message(
                    view=cards.info("Already answered", "This request was answered before."), ephemeral=True)
                return
            await interaction.response.defer()

        return callback

    async def finish(self, outcome: str) -> None:
        self.render(outcome)
        self.stop()
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)


class ApprovalManager:
    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot
        self._grants: dict[tuple[str, str], float] = {}
        self.pending = 0

    def has_grant(self, user_id: str, capability: str) -> bool:
        until = self._grants.get((user_id, capability))
        if until is None:
            return False
        if time.monotonic() >= until:
            del self._grants[(user_id, capability)]
            return False
        return True

    def clear_grants(self) -> None:
        self._grants.clear()

    async def _owners(self) -> list[discord.User]:
        found: list[discord.User] = []
        for owner_id in sorted(self.bot.owner_id_set):
            user = self.bot.get_user(owner_id)
            if user is None:
                with contextlib.suppress(discord.HTTPException):
                    user = await self.bot.fetch_user(owner_id)
            if user is not None:
                found.append(user)
        return found

    async def request(self, *, capability: str, action: str, summary: str, user: dict[str, Any],
                      timeout: float) -> tuple[bool, str]:
        user_id = str(user.get("id") or "")
        if self.has_grant(user_id, capability):
            return True, "covered by a 15 minute approval"
        lines = [
            f"**User**  {cards.truncate(user.get('name') or 'unknown', 80)}"
            + (f" ({cards.truncate(user.get('role'), 40)})" if user.get("role") else ""),
            f"**Action**  `{cards.truncate(action, 100)}`",
            f"**Needs**  `{capability}`",
        ]
        if summary:
            lines.append(f"**Details**  {cards.truncate(summary, 1200)}")
        lines.append(f"-# Unanswered requests are denied after {int(timeout // 60) or 1} min.")
        decision = _Decision()
        views: list[_ApprovalView] = []
        for owner in await self._owners():
            view = _ApprovalView(self.bot, decision, "Dashboard approval", lines, timeout)
            try:
                view.message = await owner.send(view=view, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as exc:
                log.warning("could not send the approval request to %s: %s", owner.id, exc)
                view.stop()
                continue
            views.append(view)
        if not views:
            return False, "The bot could not send a direct message to its owner. Allow DMs from the bot and try again."
        self.pending += 1
        try:
            approved, grant, who = await asyncio.wait_for(decision.future, timeout=timeout)
        except TimeoutError:
            for view in views:
                await view.finish("Not answered in time. The action was not run.")
            return False, "The approval request was not answered in time."
        finally:
            self.pending -= 1
        if approved and grant:
            self._grants[(user_id, capability)] = time.monotonic() + GRANT_SECONDS
        outcome = (f"Approved by {who}" + (" for 15 minutes." if grant else ".")) if approved else f"Denied by {who}."
        for view in views:
            await view.finish(outcome)
        return approved, outcome
