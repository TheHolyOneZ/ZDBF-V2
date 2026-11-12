# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import discord

if TYPE_CHECKING:
    from ...core.bot import ZDBFBot

Progress = Callable[[str], Awaitable[None]]
CALL_TIMEOUT = 25.0


class RateLimited(Exception):
    def __str__(self) -> str:
        return "Discord is rate limiting this change, try again in about 10 minutes"


WRITE_ERRORS = (discord.HTTPException, RateLimited)


@dataclass
class RestoreReport:
    dry_run: bool
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    roles_added: int = 0
    roles_removed: int = 0
    members_changed: int = 0
    steps: list[str] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    limited: int = 0

    def fail(self, what: str, exc: BaseException) -> None:
        self.failed += 1
        reason = "missing permissions" if isinstance(exc, discord.Forbidden) else str(exc)[:80]
        if isinstance(exc, RateLimited):
            self.limited += 1
        self.errors.append(f"{what}: {reason}")


class Restorer:
    def __init__(self, bot: ZDBFBot, guild: discord.Guild, snap: dict[str, Any], components: set[str], *,
                 sync_member_roles: bool = False, update_existing: bool = False, dry_run: bool = False,
                 progress: Progress | None = None, reason: str = "ZDBF backup restore") -> None:
        self.bot = bot
        self.guild = guild
        self.snap = snap
        self.components = components
        self.sync_member_roles = sync_member_roles
        self.update_existing = update_existing
        self.dry_run = dry_run
        self.progress = progress
        self.reason = reason
        self.report = RestoreReport(dry_run=dry_run)
        self.role_map: dict[int, discord.Role] = {}
        self.cat_map: dict[int, discord.CategoryChannel] = {}

    async def _step(self, text: str) -> None:
        self.report.steps.append(text)
        if self.progress:
            with contextlib.suppress(Exception):
                await self.progress(text)

    def _plan(self, text: str) -> None:
        self.report.created += 1
        if len(self.report.planned) < 60:
            self.report.planned.append(text)

    async def _pause(self) -> None:
        await asyncio.sleep(0.35)

    async def _call(self, request: Awaitable[Any]) -> Any:
        try:
            return await asyncio.wait_for(request, timeout=CALL_TIMEOUT)
        except TimeoutError:
            raise RateLimited from None

    @property
    def _top(self) -> discord.Role:
        return self.guild.me.top_role

    async def run(self) -> RestoreReport:
        start = time.monotonic()
        order = (
            ("roles", self._roles), ("categories", self._categories), ("channels", self._channels),
            ("emojis", self._emojis), ("stickers", self._stickers), ("server_settings", self._settings),
            ("server_images", self._images), ("member_roles", self._member_roles), ("bot_settings", self._bot_settings),
        )
        for comp in ("roles", "categories"):
            if comp not in self.components:
                self._map_existing(comp)
        for name, func in order:
            if name in self.components:
                await func()
        self.report.elapsed = time.monotonic() - start
        return self.report

    def _map_existing(self, comp: str) -> None:
        if comp == "roles":
            by_name = {r.name.lower(): r for r in self.guild.roles}
            for rd in self.snap.get("roles", []):
                if role := self.guild.get_role(rd["id"]) or by_name.get(rd["name"].lower()):
                    self.role_map[rd["id"]] = role
        else:
            by_name = {c.name.lower(): c for c in self.guild.categories}
            for cd in self.snap.get("categories", []):
                found = self.guild.get_channel(cd["id"]) or by_name.get(cd["name"].lower())
                if isinstance(found, discord.CategoryChannel):
                    self.cat_map[cd["id"]] = found

    def _overwrites(self, data: list[dict[str, Any]]) -> dict[Any, discord.PermissionOverwrite]:
        out: dict[Any, discord.PermissionOverwrite] = {}
        role_by_name = {r.name.lower(): r for r in self.guild.roles}
        for ow in data:
            target: Any = None
            if ow["target_type"] == "role":
                target = self.role_map.get(ow["target_id"]) or self.guild.get_role(ow["target_id"])
                if target is None and ow.get("target_name"):
                    target = role_by_name.get(str(ow["target_name"]).lower())
                if target is None and ow["target_id"] == self.snap.get("guild", {}).get("id"):
                    target = self.guild.default_role
            else:
                target = self.guild.get_member(ow["target_id"])
            if target is not None:
                out[target] = discord.PermissionOverwrite.from_pair(discord.Permissions(ow["allow"]),
                                                                    discord.Permissions(ow["deny"]))
        return out

    async def _roles(self) -> None:
        roles = self.snap.get("roles", [])
        await self._step(f"Roles ({len(roles)})")
        existing = {r.name.lower(): r for r in self.guild.roles}
        for rd in reversed(roles):
            current = existing.get(rd["name"].lower())
            if current is not None:
                self.role_map[rd["id"]] = current
                if self.update_existing and current < self._top and not current.managed:
                    changes = {}
                    if current.colour.value != rd.get("color", 0):
                        changes["colour"] = discord.Colour(rd.get("color", 0))
                    if current.permissions.value != rd.get("permissions_value", 0):
                        changes["permissions"] = discord.Permissions(rd.get("permissions_value", 0))
                    if current.hoist != rd.get("hoist", False):
                        changes["hoist"] = rd.get("hoist", False)
                    if current.mentionable != rd.get("mentionable", False):
                        changes["mentionable"] = rd.get("mentionable", False)
                    if changes:
                        if self.dry_run:
                            self.report.updated += 1
                            continue
                        try:
                            await self._call(current.edit(reason=self.reason, **changes))
                            self.report.updated += 1
                            await self._pause()
                        except WRITE_ERRORS as exc:
                            self.report.fail(f"role {rd['name']}", exc)
                        continue
                self.report.skipped += 1
                continue
            if self.dry_run:
                self._plan(f"role @{rd['name']}")
                continue
            try:
                kwargs: dict[str, Any] = {}
                if rd.get("unicode_emoji") and "ROLE_ICONS" in self.guild.features:
                    kwargs["display_icon"] = rd["unicode_emoji"]
                role = await self._call(self.guild.create_role(
                    name=rd["name"], colour=discord.Colour(rd.get("color", 0)), hoist=rd.get("hoist", False),
                    mentionable=rd.get("mentionable", False), permissions=discord.Permissions(rd.get("permissions_value", 0)),
                    reason=self.reason, **kwargs))
                self.role_map[rd["id"]] = role
                self.report.created += 1
                await self._pause()
            except WRITE_ERRORS as exc:
                self.report.fail(f"role {rd['name']}", exc)
        if self.update_existing and "default_role_permissions" in self.snap and not self.dry_run:
            with contextlib.suppress(*WRITE_ERRORS):
                await self._call(self.guild.default_role.edit(permissions=discord.Permissions(self.snap["default_role_permissions"]),
                                                   reason=self.reason))
        if not self.dry_run:
            await self._reorder_roles(roles)

    async def _reorder_roles(self, roles: list[dict[str, Any]]) -> None:
        movable = [self.role_map[rd["id"]] for rd in roles
                   if rd["id"] in self.role_map and self.role_map[rd["id"]] < self._top]
        if len(movable) < 2:
            return
        top = self._top.position - 1
        positions = {role: max(1, top - i) for i, role in enumerate(movable)}
        with contextlib.suppress(*WRITE_ERRORS):
            await self._call(self.guild.edit_role_positions(positions=positions, reason=self.reason))  # type: ignore[arg-type]

    async def _categories(self) -> None:
        cats = self.snap.get("categories", [])
        await self._step(f"Categories ({len(cats)})")
        existing = {c.name.lower(): c for c in self.guild.categories}
        for cd in sorted(cats, key=lambda c: c.get("position", 0)):
            current = existing.get(cd["name"].lower())
            if current is not None:
                self.cat_map[cd["id"]] = current
                wanted = self._overwrites(cd.get("overwrites", []))
                if self.update_existing and current.overwrites != wanted:
                    if self.dry_run:
                        self.report.updated += 1
                        continue
                    try:
                        await self._call(current.edit(overwrites=wanted, reason=self.reason))
                        self.report.updated += 1
                        await self._pause()
                    except WRITE_ERRORS as exc:
                        self.report.fail(f"category {cd['name']}", exc)
                    continue
                self.report.skipped += 1
                continue
            if self.dry_run:
                self._plan(f"category {cd['name']}")
                continue
            try:
                self.cat_map[cd["id"]] = await self._call(self.guild.create_category(
                    cd["name"], overwrites=self._overwrites(cd.get("overwrites", [])), position=cd.get("position"),
                    reason=self.reason))
                self.report.created += 1
                await self._pause()
            except WRITE_ERRORS as exc:
                self.report.fail(f"category {cd['name']}", exc)

    def _channel_changes(self, current: Any, cd: dict[str, Any], key: str) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        wanted = self._overwrites(cd.get("overwrites", []))
        if current.overwrites != wanted:
            changes["overwrites"] = wanted
        if key == "text_channels":
            if (current.topic or None) != (cd.get("topic") or None):
                changes["topic"] = cd.get("topic")
            if current.slowmode_delay != cd.get("slowmode_delay", 0):
                changes["slowmode_delay"] = cd.get("slowmode_delay", 0)
            if current.nsfw != cd.get("nsfw", False):
                changes["nsfw"] = cd.get("nsfw", False)
        return changes

    async def _channels(self) -> None:
        kinds = (
            ("text_channels", self.guild.text_channels, "#"),
            ("voice_channels", self.guild.voice_channels, "voice: "),
            ("forum_channels", self.guild.forums, "forum: "),
            ("stage_channels", self.guild.stage_channels, "stage: "),
        )
        total = sum(len(self.snap.get(k, [])) for k, _, _ in kinds)
        await self._step(f"Channels ({total})")
        for key, existing_list, icon in kinds:
            existing = {c.name.lower(): c for c in existing_list}
            for cd in sorted(self.snap.get(key, []), key=lambda c: c.get("position", 0)):
                category = self.cat_map.get(cd.get("category_id") or 0)
                current = existing.get(cd["name"].lower())
                if current is not None:
                    kwargs = self._channel_changes(current, cd, key) if self.update_existing else {}
                    if kwargs:
                        if self.dry_run:
                            self.report.updated += 1
                            continue
                        try:
                            await self._call(current.edit(reason=self.reason, **kwargs))  # type: ignore[union-attr]
                            self.report.updated += 1
                            await self._pause()
                        except WRITE_ERRORS as exc:
                            self.report.fail(f"{icon}{cd['name']}", exc)
                        continue
                    self.report.skipped += 1
                    continue
                if self.dry_run:
                    self._plan(f"{icon}{cd['name']}" + (f" in {category.name}" if category else ""))
                    continue
                overwrites = self._overwrites(cd.get("overwrites", []))
                try:
                    match key:
                        case "text_channels":
                            await self._call(self.guild.create_text_channel(
                                cd["name"], category=category, topic=cd.get("topic"), nsfw=cd.get("nsfw", False),
                                slowmode_delay=cd.get("slowmode_delay", 0), overwrites=overwrites,
                                news=cd.get("news", False) and "NEWS" in self.guild.features, reason=self.reason))
                        case "voice_channels":
                            await self._call(self.guild.create_voice_channel(
                                cd["name"], category=category, bitrate=min(cd.get("bitrate", 64000),
                                                                           int(self.guild.bitrate_limit)),
                                user_limit=cd.get("user_limit", 0), rtc_region=cd.get("rtc_region"),
                                overwrites=overwrites, reason=self.reason))
                        case "forum_channels":
                            tags = [discord.ForumTag(name=t["name"], emoji=t.get("emoji"), moderated=t.get("moderated", False))
                                    for t in cd.get("tags", [])][:20]
                            await self._call(self.guild.create_forum(
                                cd["name"], category=category, topic=cd.get("topic"), nsfw=cd.get("nsfw", False),
                                slowmode_delay=cd.get("slowmode_delay", 0), overwrites=overwrites,
                                available_tags=tags, reason=self.reason))
                        case "stage_channels":
                            await self._call(self.guild.create_stage_channel(cd["name"], category=category, overwrites=overwrites,
                                                                  reason=self.reason))
                    self.report.created += 1
                    await self._pause()
                except WRITE_ERRORS as exc:
                    self.report.fail(f"{icon}{cd['name']}", exc)

    async def _emojis(self) -> None:
        emojis = self.snap.get("emojis", [])
        await self._step(f"Emojis ({len(emojis)})")
        existing = {e.name.lower() for e in self.guild.emojis}
        free = {False: self.guild.emoji_limit - sum(not e.animated for e in self.guild.emojis),
                True: self.guild.emoji_limit - sum(e.animated for e in self.guild.emojis)}
        for ed in emojis:
            if ed["name"].lower() in existing:
                self.report.skipped += 1
                continue
            if not ed.get("image_b64"):
                self.report.fail(f"emoji :{ed['name']}:", RuntimeError("no image data in backup"))
                continue
            if free[ed.get("animated", False)] <= 0:
                self.report.fail(f"emoji :{ed['name']}:", RuntimeError("no free emoji slots"))
                continue
            if self.dry_run:
                self._plan(f"emoji :{ed['name']}:")
                free[ed.get("animated", False)] -= 1
                continue
            try:
                await self._call(self.guild.create_custom_emoji(name=ed["name"], image=base64.b64decode(ed["image_b64"]),
                                                     reason=self.reason))
                free[ed.get("animated", False)] -= 1
                self.report.created += 1
                await self._pause()
            except WRITE_ERRORS as exc:
                self.report.fail(f"emoji :{ed['name']}:", exc)

    async def _stickers(self) -> None:
        stickers = self.snap.get("stickers", [])
        await self._step(f"Stickers ({len(stickers)})")
        existing = {s.name.lower() for s in self.guild.stickers}
        free = self.guild.sticker_limit - len(self.guild.stickers)
        for sd in stickers:
            if sd["name"].lower() in existing:
                self.report.skipped += 1
                continue
            if not sd.get("image_b64") or sd.get("format") == "lottie" or free <= 0:
                self.report.fail(f"sticker {sd['name']}", RuntimeError("no data, unsupported format or no free slots"))
                continue
            if self.dry_run:
                self._plan(f"sticker {sd['name']}")
                free -= 1
                continue
            ext = {"png": "png", "apng": "png", "gif": "gif"}.get(str(sd.get("format", "png")).lower(), "png")
            try:
                await self._call(self.guild.create_sticker(
                    name=sd["name"], description=sd.get("description") or sd["name"], emoji=sd.get("emoji") or "⭐",
                    file=discord.File(io.BytesIO(base64.b64decode(sd["image_b64"])), filename=f"sticker.{ext}"),
                    reason=self.reason))
                free -= 1
                self.report.created += 1
                await self._pause()
            except WRITE_ERRORS as exc:
                self.report.fail(f"sticker {sd['name']}", exc)

    def _channel_named(self, name: str | None, kind: type) -> Any:
        if not name:
            return None
        return next((c for c in self.guild.channels if isinstance(c, kind) and c.name == name), None)

    async def _settings(self) -> None:
        s = self.snap.get("server_settings") or {}
        if not s:
            return
        await self._step("Server settings")
        if self.dry_run:
            self.report.planned.append("server settings (verification, notifications, AFK, system channels…)")
            return
        edits: dict[str, Any] = {
            "verification_level": discord.VerificationLevel(s.get("verification_level", 0)),
            "default_notifications": discord.NotificationLevel(s.get("default_notifications", 0)),
            "explicit_content_filter": discord.ContentFilter(s.get("explicit_content_filter", 0)),
            "afk_timeout": s.get("afk_timeout", 300),
            "premium_progress_bar_enabled": s.get("premium_progress_bar_enabled", False),
        }
        if afk := self._channel_named(s.get("afk_channel"), discord.VoiceChannel):
            edits["afk_channel"] = afk
        if system := self._channel_named(s.get("system_channel"), discord.TextChannel):
            edits["system_channel"] = system
        try:
            await self._call(self.guild.edit(reason=self.reason, **edits))
            self.report.updated += 1
        except WRITE_ERRORS as exc:
            self.report.fail("server settings", exc)
        if "COMMUNITY" in self.guild.features:
            community: dict[str, Any] = {}
            if rules := self._channel_named(s.get("rules_channel"), discord.TextChannel):
                community["rules_channel"] = rules
            if updates := self._channel_named(s.get("public_updates_channel"), discord.TextChannel):
                community["public_updates_channel"] = updates
            if s.get("description"):
                community["description"] = s["description"]
            if community:
                try:
                    await self._call(self.guild.edit(reason=self.reason, **community))
                except WRITE_ERRORS as exc:
                    self.report.fail("community settings", exc)

    async def _images(self) -> None:
        g = self.snap.get("guild", {})
        if not g.get("icon_b64") and not g.get("banner_b64"):
            return
        await self._step("Icon & banner")
        if self.dry_run:
            self.report.planned.append("server icon" + (" and banner" if g.get("banner_b64") else ""))
            return
        edits: dict[str, Any] = {}
        if g.get("icon_b64"):
            edits["icon"] = base64.b64decode(g["icon_b64"])
        if g.get("banner_b64") and self.guild.premium_tier >= 2:
            edits["banner"] = base64.b64decode(g["banner_b64"])
        try:
            await self._call(self.guild.edit(reason=self.reason, **edits))
            self.report.updated += 1
        except WRITE_ERRORS as exc:
            self.report.fail("icon/banner", exc)

    async def _member_roles(self) -> None:
        data = self.snap.get("member_roles", [])
        await self._step(f"Member roles ({len(data)} members{' · sync' if self.sync_member_roles else ''})")
        if not self.guild.chunked:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.guild.chunk(cache=True), timeout=60)
        names = {rd["id"]: rd["name"] for rd in self.snap.get("roles", [])}
        by_name = {r.name.lower(): r for r in self.guild.roles if not r.is_default() and not r.managed}

        def resolve(old_id: int, old_name: str | None) -> discord.Role | None:
            role = self.role_map.get(old_id) or self.guild.get_role(old_id)
            if role is not None and not role.is_default() and not role.managed:
                return role
            name = old_name or names.get(old_id)
            return by_name.get(name.lower()) if name else None

        for i, md in enumerate(data):
            member = self.guild.get_member(md["user_id"])
            if member is None or member.bot:
                continue
            role_names = md.get("role_names", [])
            targets = [r for j, rid in enumerate(md.get("role_ids", []))
                       if (r := resolve(rid, role_names[j] if j < len(role_names) else None)) is not None]
            add = [r for r in targets if r not in member.roles and r < self._top]
            remove = []
            if self.sync_member_roles:
                wanted = {r.id for r in targets}
                remove = [r for r in member.roles if not r.is_default() and not r.managed and r < self._top
                          and r.id not in wanted]
            if not add and not remove:
                continue
            if self.dry_run:
                self.report.roles_added += len(add)
                self.report.roles_removed += len(remove)
                self.report.members_changed += 1
                continue
            try:
                if add:
                    await self._call(member.add_roles(*add, reason=self.reason))
                if remove:
                    await self._call(member.remove_roles(*remove, reason=self.reason))
                self.report.roles_added += len(add)
                self.report.roles_removed += len(remove)
                self.report.members_changed += 1
                await self._pause()
            except WRITE_ERRORS as exc:
                self.report.fail(f"member {md.get('username', md['user_id'])}", exc)
            if i and i % 50 == 0:
                await self._step(f"Member roles · {i}/{len(data)}")

    async def _bot_settings(self) -> None:
        s = self.snap.get("bot_settings") or {}
        if not s:
            return
        await self._step("Bot settings")
        if self.dry_run:
            self.report.planned.append("prefix, mention prefix and command permissions")
            return
        db = self.bot.db
        await db.set_guild_prefix(self.guild.id, s.get("custom_prefix"))
        if s.get("mention_prefix_enabled") is not None:
            await db.set_guild_mention_prefix_enabled(self.guild.id, s["mention_prefix_enabled"])
        by_name = {r.name: r for r in self.guild.roles}
        for command, role_names in (s.get("command_permissions") or {}).items():
            for name in role_names:
                if role := by_name.get(name):
                    await db.add_command_role(self.guild.id, command, role.id)
        self.bot.prefix_cache.invalidate(self.guild.id)
        self.bot.invalidate_permissions(self.guild.id)
        self.report.updated += 1
