# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import discord

from ...ui import cards
from .engine import member_values, render

if TYPE_CHECKING:
    from .cog import Automations


def _cog(interaction: discord.Interaction[Any]) -> Automations | None:
    return interaction.client.get_cog("Automations")  # type: ignore[attr-defined,return-value]


async def _deny(interaction: discord.Interaction[Any], title: str, text: str) -> None:
    await interaction.response.send_message(view=cards.error(title, text), ephemeral=True)


class RoleButton(discord.ui.DynamicItem[discord.ui.Button[Any]], template=r"zdbf:rb:(?P<hook>[0-9a-f]+):(?P<role>\d+)"):
    def __init__(self, hook_id: str, role_id: int, label: str | None = None) -> None:
        super().__init__(discord.ui.Button(label=(label or "Role")[:80], style=discord.ButtonStyle.secondary,
                                           custom_id=f"zdbf:rb:{hook_id}:{role_id}"))
        self.hook_id = hook_id
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction[Any], item: discord.ui.Button[Any],
                             match: Any) -> RoleButton:
        return cls(match["hook"], int(match["role"]), item.label)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        cog = _cog(interaction)
        auto = cog.find(self.hook_id) if cog else None
        member = interaction.user
        if auto is None or not auto.enabled or not isinstance(member, discord.Member) or interaction.guild is None:
            await _deny(interaction, "Unavailable", "This role panel is disabled.")
            return
        role = interaction.guild.get_role(self.role_id)
        if role is None or role >= interaction.guild.me.top_role:
            await _deny(interaction, "Can't assign", "That role no longer exists or is above my highest role.")
            return
        if role in member.roles:
            await member.remove_roles(role, reason=f"Button roles: {auto.name}")
            text = f"Removed {role.mention}."
        else:
            if auto.config.get("exclusive"):
                panel_roles = {int(r) for r in auto.config.get("roles", [])}
                others = [r for r in member.roles if r.id in panel_roles and r != role]
                if others:
                    await member.remove_roles(*others, reason=f"Button roles (exclusive): {auto.name}")
            await member.add_roles(role, reason=f"Button roles: {auto.name}")
            text = f"Added {role.mention}."
        await interaction.response.send_message(view=cards.success("Roles updated", text), ephemeral=True)


class TicketOpenButton(discord.ui.DynamicItem[discord.ui.Button[Any]], template=r"zdbf:tk:open:(?P<hook>[0-9a-f]+)"):
    def __init__(self, hook_id: str) -> None:
        super().__init__(discord.ui.Button(label="Open ticket", style=discord.ButtonStyle.primary,
                                           custom_id=f"zdbf:tk:open:{hook_id}"))
        self.hook_id = hook_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction[Any], item: discord.ui.Button[Any],
                             match: Any) -> TicketOpenButton:
        return cls(match["hook"])

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        cog = _cog(interaction)
        auto = cog.find(self.hook_id) if cog else None
        guild = interaction.guild
        member = interaction.user
        if auto is None or not auto.enabled or guild is None or not isinstance(member, discord.Member):
            await _deny(interaction, "Unavailable", "Tickets are currently disabled.")
            return
        assert cog is not None
        existing = await cog.runtime.state_get(auto, member.id, "open_ticket")
        if existing and guild.get_channel(int(existing)):
            await _deny(interaction, "Ticket already open", f"You already have one: <#{existing}>")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        c = auto.config
        support = guild.get_role(int(c.get("support_role_id") or 0))
        overwrites: dict[Any, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True,
                                                read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if support:
            overwrites[support] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                              read_message_history=True)
        category = guild.get_channel(int(c.get("category_id") or 0))
        values = member_values(member, guild)
        name = render(c.get("name_template", "ticket-{username}"), **values).lower().replace(" ", "-")[:90]
        channel = await guild.create_text_channel(
            name, overwrites=overwrites, category=category if isinstance(category, discord.CategoryChannel) else None,
            reason=f"Ticket opened by {member}", topic=f"Ticket for {member} ({member.id})")
        await cog.runtime.state_set(auto, member.id, "open_ticket", channel.id)
        await cog.runtime.state_set(auto, channel.id, "ticket_owner", member.id)
        box = cards.card("Ticket", render(c.get("welcome", "Hi {user}."), **values),
                         foot=f"Opened {cards.timestamp()}")
        box.add_item(discord.ui.ActionRow(TicketCloseButton(auto.hook_id)))
        await channel.send(content=f"{member.mention}" + (f" {support.mention}" if support else ""),
                           view=None, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        await channel.send(view=cards.static(box))
        await interaction.followup.send(view=cards.success("Ticket created", f"Head over to {channel.mention}."),
                                        ephemeral=True)


class TicketCloseButton(discord.ui.DynamicItem[discord.ui.Button[Any]], template=r"zdbf:tk:close:(?P<hook>[0-9a-f]+)"):
    def __init__(self, hook_id: str) -> None:
        super().__init__(discord.ui.Button(label="Close ticket", style=discord.ButtonStyle.danger,
                                           custom_id=f"zdbf:tk:close:{hook_id}"))
        self.hook_id = hook_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction[Any], item: discord.ui.Button[Any],
                             match: Any) -> TicketCloseButton:
        return cls(match["hook"])

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        cog = _cog(interaction)
        auto = cog.find(self.hook_id) if cog else None
        channel = interaction.channel
        member = interaction.user
        if auto is None or cog is None or not isinstance(channel, discord.TextChannel) or not isinstance(member, discord.Member):
            await _deny(interaction, "Unavailable", "This ticket can't be closed from here.")
            return
        owner = await cog.runtime.state_get(auto, channel.id, "ticket_owner")
        support_id = int(auto.config.get("support_role_id") or 0)
        allowed = member.id == owner or any(r.id == support_id for r in member.roles) \
            or member.guild_permissions.manage_channels
        if not allowed:
            await _deny(interaction, "Not allowed", "Only the ticket owner or support team can close it.")
            return
        await interaction.response.send_message(view=cards.warning("Closing", "This channel is deleted in 5 seconds."))
        if owner:
            await cog.runtime.state_delete(auto, int(owner), "open_ticket")
        await cog.runtime.state_delete(auto, channel.id, "ticket_owner")
        await asyncio.sleep(5)
        with contextlib.suppress(discord.HTTPException):
            await channel.delete(reason=f"Ticket closed by {member}")


PERSISTENT_ITEMS = (RoleButton, TicketOpenButton, TicketCloseButton)
