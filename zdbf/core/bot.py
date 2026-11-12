# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import copy
import hashlib
import json
import logging
import sys
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .. import __version__
from ..ui import cards
from .alerts import AlertManager
from .cache import TTLCache
from .config import Config
from .database import Database
from .errors import handle_app_command_error, handle_command_error
from .extensions import ExtensionManager, accept_old_setup
from .hooks import HookBus
from .logging import cleanup_old_logs
from .metrics import MetricsCollector
from .permissions import is_owner_only, parent_checks, role_permission_check
from .plugins import PluginMetadata, PluginRegistry
from .slash_guard import SLASH_LIMIT, GuardedTree, SlashGuard
from .storage import __name__ as _storage_module

sys.modules.setdefault("atomic_file_system", sys.modules[_storage_module])

log = logging.getLogger("zdbf.bot")

__all__ = ["ACTING_AS_OWNER", "ZDBFBot"]

ACTING_AS_OWNER: contextvars.ContextVar[bool] = contextvars.ContextVar("zdbf_acting_as_owner", default=False)

REPO_URL = "https://github.com/TheHolyOneZ/ZDBF-V2"


class ZDBFTree(GuardedTree):
    async def on_error(self, interaction: discord.Interaction[ZDBFBot],
                       error: app_commands.AppCommandError) -> None:
        await handle_app_command_error(self.client, interaction, error)


class ZDBFBot(commands.AutoShardedBot):
    def __init__(self, config: Config) -> None:
        self.config = config
        intents = discord.Intents.default()
        privileged = set(config.settings.bot.privileged_intents)
        intents.members = "members" in privileged
        intents.message_content = "message_content" in privileged
        intents.presences = "presences" in privileged

        super().__init__(
            command_prefix=ZDBFBot._resolve_prefix,
            intents=intents,
            help_command=None,
            case_insensitive=True,
            strip_after_prefix=True,
            tree_cls=ZDBFTree,
            shard_count=config.secrets.shard_count,
            shard_ids=config.secrets.shard_ids,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
            max_messages=1000,
        )
        self.version = __version__
        self.repo_url = REPO_URL
        self.db = Database(config.settings.database.path, backup_keep=config.settings.maintenance.db_backup_keep)
        self.metrics = MetricsCollector()
        self.hooks = HookBus(self)
        self.plugins = PluginRegistry(self)
        self.alerts = AlertManager(self)
        self.slash_guard = SlashGuard(self)
        self.ext = ExtensionManager(self)
        self.prefix_cache: TTLCache[int, tuple[str, bool]] = TTLCache(ttl=600)
        self._perm_cache: TTLCache[int, dict[str, list[int]]] = TTLCache(ttl=300)
        self._app_owner_ids: set[int] = set()
        self._ready_once = False
        self._background: list[asyncio.Task[Any]] = []
        self._sync_task: asyncio.Task[None] | None = None
        self.started_at = time.time()
        self.legacy_aliases: dict[str, str] = {}
        self.add_check(parent_checks)
        self.add_check(role_permission_check)
        self.add_check(self._default_cooldown, call_once=True)
        self._cooldown_maps: dict[str, commands.CooldownMapping[Any]] = {}
        cards.set_decorative_emoji(config.settings.ui.decorative_emoji)

    async def _load_from_module_spec(self, spec: Any, key: str) -> None:
        accept_old_setup(spec, key)
        await super()._load_from_module_spec(spec, key)

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.alerts.load()
        if self.db.recovered is not None:
            moved, restored = self.db.recovered
            text = (f"The database was replaced on start. Previous file kept as `{moved}`; "
                    + (f"restored from `{restored}`." if restored else "no backup was available, started empty."))

            async def announce() -> None:
                await self.wait_until_ready()
                await self.alerts.send("database", text, "critical")

            self._background.append(asyncio.create_task(announce(), name="zdbf-db-recovery-alert"))
        await self.plugins.load_settings()
        await self.hooks.load_disabled()
        self.hooks.start()
        await self._load_app_owners()

        results = await self.ext.load_builtin()
        if self.config.settings.extensions.auto_load:
            results += await self.ext.load_user_extensions()
        ok = sum(r.ok for r in results)
        failed = [r for r in results if not r.ok]
        log.info("modules & extensions: %d loaded, %d failed", ok, len(failed))
        for r in failed:
            log.warning("  ✗ %s: %s", r.name, r.error)

        if self.config.settings.extensions.hot_reload:
            self.ext.start_watcher()
        self._background += [
            asyncio.create_task(self._status_loop(), name="zdbf-status"),
            asyncio.create_task(self._maintenance_loop(), name="zdbf-maintenance"),
        ]
        if self.config.settings.bot.sync_on_start:
            try:
                await self.sync_commands()
            except discord.HTTPException as exc:
                log.error("initial slash command sync failed: %s", exc)

    async def _load_app_owners(self) -> None:
        try:
            app = await self.application_info()
        except discord.HTTPException:
            return
        if app.team:
            self._app_owner_ids = {m.id for m in app.team.members}
        elif app.owner:
            self._app_owner_ids = {app.owner.id}

    @property
    def owner_id_set(self) -> set[int]:
        return self.config.owner_ids | self._app_owner_ids

    @property
    def bot_owner_id(self) -> int:
        ids = sorted(self.config.secrets.owner_ids) or sorted(self.owner_id_set)
        return ids[0] if ids else 0

    async def is_owner(self, user: discord.abc.User, /) -> bool:
        if ACTING_AS_OWNER.get() and self.user is not None and user.id == self.user.id:
            return True
        if not self._app_owner_ids:
            await self._load_app_owners()
        return user.id in self.owner_id_set

    async def _resolve_prefix(self, message: discord.Message) -> list[str]:
        prefix, mention = await self.guild_prefix(message.guild.id if message.guild else None)
        prefixes = [prefix]
        if mention:
            prefixes = commands.when_mentioned_or(prefix)(self, message)
        return prefixes

    async def guild_prefix(self, guild_id: int | None) -> tuple[str, bool]:
        default = (self.config.settings.bot.prefix, self.config.settings.bot.mention_prefix)
        if guild_id is None:
            return default
        cached = self.prefix_cache.get(guild_id)
        if cached is not None:
            return cached
        prefix = await self.db.get_guild_prefix(guild_id) or default[0]
        mention = await self.db.get_guild_mention_prefix_enabled(guild_id)
        value = (prefix, default[1] if mention is None else mention)
        self.prefix_cache.set(guild_id, value)
        return value

    async def get_permission_table(self, guild_id: int) -> dict[str, list[int]]:
        table = self._perm_cache.get(guild_id)
        if table is None:
            table = await self.db.list_command_permissions(guild_id)
            self._perm_cache.set(guild_id, table)
        return table

    def invalidate_permissions(self, guild_id: int) -> None:
        self._perm_cache.invalidate(guild_id)

    async def on_ready(self) -> None:
        assert self.user is not None
        if self._ready_once:
            log.info("reconnected as %s", self.user)
            return
        self._ready_once = True
        log.info(
            "ready as %s (%s) | %d guilds | %d shard(s) | ZDBF %s | discord.py %s",
            self.user, self.user.id, len(self.guilds), self.shard_count or 1, self.version, discord.__version__,
        )
        await self.hooks.emit("bot_ready", bot_user=self.user)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("joined guild %s (%s) | members: %s", guild.name, guild.id, guild.member_count)
        await self.hooks.emit("guild_joined", guild=guild)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        log.info("left guild %s (%s)", guild.name, guild.id)
        self.prefix_cache.invalidate(guild.id)
        self.invalidate_permissions(guild.id)
        await self.db.cleanup_guild(guild.id)
        await self.hooks.emit("guild_left", guild=guild)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        self.metrics.record_message()
        if self.user and message.content.strip() in (f"<@{self.user.id}>", f"<@!{self.user.id}>"):
            await self._send_intro(message)
            return
        await self.process_commands(message)

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        self.metrics.record_interaction()

    async def _send_intro(self, message: discord.Message) -> None:
        prefix, _ = await self.guild_prefix(message.guild.id if message.guild else None)
        assert self.user is not None
        box = cards.card(
            self.user.display_name,
            cards.kv({"Prefix": f"`{prefix}`", "Slash": "`/` (always available)",
                      "Shards": self.shard_count or 1}),
            cards.sep(),
            f"Use **`{prefix}help`** or **`/help`** to see every command.\n"
            f"Use **`{prefix}about`** or **`/about`** for framework info & credits.",
            subtitle=f"Built on ZDBF {self.version}",
            thumbnail=self.user.display_avatar.url,
            accent="brand",
            foot=f"Serving {len(self.guilds)} servers · {self.latency * 1000:.0f} ms · Created by TheHolyOneZ",
        )
        from ..ui.base import link_button, row

        box.add_item(row(link_button("Repository", REPO_URL)))
        with contextlib.suppress(discord.HTTPException):
            await message.channel.send(view=cards.static(box), allowed_mentions=discord.AllowedMentions.none())

    async def get_context(self, origin: Any, /, *, cls: type[commands.Context[Any]] = commands.Context) -> Any:
        ctx = await super().get_context(origin, cls=cls)
        if (
            ctx.command is None
            and ctx.invoked_with
            and ctx.prefix
            and isinstance(origin, discord.Message)
            and (target := self.legacy_aliases.get(ctx.invoked_with.lower()))
        ):
            rest = origin.content[len(ctx.prefix) + len(ctx.invoked_with):]
            rewritten = copy.copy(origin)
            rewritten.content = f"{ctx.prefix}{target}{rest}"
            ctx = await super().get_context(rewritten, cls=cls)
        return ctx

    async def on_command(self, ctx: commands.Context[Any]) -> None:
        assert ctx.command is not None
        name = ctx.command.qualified_name
        self.metrics.record_command(name)
        log.info("command %s | %s (%s) | guild %s", name, ctx.author, ctx.author.id, ctx.guild.id if ctx.guild else "DM")
        try:
            await self.db.increment_command_usage(name, ctx.guild.id if ctx.guild else None)
        except Exception:
            log.debug("could not record command usage", exc_info=True)
        await self.hooks.emit("command_executed", command_name=name, author=ctx.author, guild=ctx.guild, ctx=ctx)

    async def on_command_completion(self, ctx: commands.Context[Any]) -> None:
        if (
            self.config.settings.bot.delete_invoking_message
            and ctx.interaction is None
            and ctx.guild is not None
        ):
            with contextlib.suppress(discord.HTTPException):
                await ctx.message.delete()

    async def on_command_error(self, ctx: commands.Context[Any], error: commands.CommandError) -> None:
        await self.hooks.emit(
            "command_error",
            command_name=ctx.command.qualified_name if ctx.command else "unknown",
            error=error, author=ctx.author, guild=ctx.guild,
        )
        await handle_command_error(self, ctx, error)

    def _prepare_tree(self) -> None:
        dev_guilds = [discord.Object(g) for g in self.config.settings.bot.dev_guild_ids]
        for command in self.commands:
            app = getattr(command, "app_command", None)
            if app is None or not is_owner_only(command):
                continue
            app.default_permissions = discord.Permissions(administrator=True)
            if dev_guilds and self.tree.get_command(app.name) is not None:
                self.tree.remove_command(app.name)
                for guild in dev_guilds:
                    self.tree.add_command(app, guild=guild, override=True)
        self.slash_guard.enforce([None, *dev_guilds])

    def _tree_hash(self, guild: discord.abc.Snowflake | None) -> str:
        payload = sorted(
            (c.to_dict(self.tree) for c in self.tree.get_commands(guild=guild)),
            key=lambda d: (d.get("type", 1), d["name"]),
        )
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    async def sync_commands(self, *, force: bool = False) -> dict[str, int]:
        self._prepare_tree()
        if new := self.slash_guard.newly_demoted:
            self.slash_guard.newly_demoted = []
            await self.alerts.send(
                "diagnostics", f"More than {SLASH_LIMIT} slash commands are registered. {len(new)} command(s) now work "
                f"with the prefix only: {', '.join(new[:20])}{' ...' if len(new) > 20 else ''}. See /diag commands.",
                "warning")
        targets: list[discord.abc.Snowflake | None] = [None]
        targets += [discord.Object(g) for g in self.config.settings.bot.dev_guild_ids]
        done: dict[str, int] = {}
        stored: dict[str, str] = await self.db.kv_get("tree.hashes", {})
        for target in targets:
            key = "global" if target is None else str(target.id)
            digest = self._tree_hash(target)
            if not force and stored.get(key) == digest:
                continue
            synced = await self.tree.sync(guild=target)
            stored[key] = digest
            done[key] = len(synced)
            log.info("synced %d slash commands (%s)", len(synced), key)
        await self.db.kv_set("tree.hashes", stored)
        return done

    def mark_tree_dirty(self) -> None:
        self.dispatch("zdbf_extensions_changed")
        if not self.is_ready():
            return
        if self._sync_task is not None and not self._sync_task.done():
            self._sync_task.cancel()
        self._sync_task = asyncio.create_task(self._debounced_sync())

    async def _debounced_sync(self) -> None:
        await asyncio.sleep(10)
        try:
            await self.sync_commands()
        except discord.HTTPException as exc:
            log.warning("auto sync failed: %s", exc)

    def slash_command_count(self) -> dict[str, int]:
        top = self.tree.get_commands(type=discord.AppCommandType.chat_input)
        total = sum(1 + (sum(1 for _ in c.walk_commands()) if isinstance(c, app_commands.Group) else 0)
                    for c in top)
        return {"top_level": len(top), "limit": SLASH_LIMIT, "with_subcommands": total,
                "demoted": len(self.slash_guard.demoted)}

    def format_status(self, text: str) -> str:
        values = {
            "guilds": len(self.guilds),
            "users": sum(g.member_count or 0 for g in self.guilds),
            "shards": self.shard_count or 1,
            "commands": len(self.commands),
            "prefix": self.config.settings.bot.prefix,
            "version": self.version,
        }
        with contextlib.suppress(KeyError, IndexError, ValueError):
            return text.format(**values)
        return text

    async def _status_loop(self) -> None:
        await self.wait_until_ready()
        index = 0
        while not self.is_closed():
            settings = self.config.settings.status
            if settings.rotation:
                entry = settings.rotation[index % len(settings.rotation)]
                index += 1
                text = self.format_status(entry.text)
                activity: discord.BaseActivity
                if entry.type == "custom":
                    activity = discord.CustomActivity(name=text)
                else:
                    activity = discord.Activity(type=getattr(discord.ActivityType, entry.type), name=text)
                with contextlib.suppress(Exception):
                    await self.change_presence(status=discord.Status(entry.presence), activity=activity)
            await asyncio.sleep(settings.interval)

    async def _maintenance_loop(self) -> None:
        await self.wait_until_ready()
        last_backup = 0.0
        while not self.is_closed():
            await asyncio.sleep(3600)
            due = time.time() - last_backup >= self.config.settings.maintenance.db_backup_interval_hours * 3600
            try:
                await self.run_maintenance(backup_due=due)
                if due:
                    last_backup = time.time()
            except Exception:
                log.exception("maintenance run failed")

    async def run_maintenance(self, *, backup_due: bool = False) -> dict[str, int]:
        m = self.config.settings.maintenance
        report = {"expired_cache": self.prefix_cache.cleanup_expired() + self._perm_cache.cleanup_expired(),
                  "old_logs": cleanup_old_logs(self.config.settings.logging.directory,
                                               self.config.settings.logging.retention_days),
                  "pycache": 0, "legacy_connections": 0, "backup": 0}
        if m.clean_pycache:
            import shutil

            for d in (self.ext.directory.rglob("__pycache__") if self.ext.directory.exists() else ()):
                shutil.rmtree(d, ignore_errors=True)
                report["pycache"] += 1
        active = {g.id for g in self.guilds}
        for guild_id in [g for g in self.db._legacy_guild_conns if g not in active]:
            await self.db.cleanup_guild(guild_id)
            report["legacy_connections"] += 1
        await self.db.checkpoint()
        await self.db.execute("PRAGMA optimize")
        if backup_due:
            await self.db.backup()
            report["backup"] = 1
        return report

    async def close(self) -> None:
        log.info("shutting down…")
        await self.ext.stop_watcher()
        for task in self._background:
            task.cancel()
        if self._sync_task is not None:
            self._sync_task.cancel()
        await self.hooks.stop()
        await super().close()
        await self.db.close()
        log.info("goodbye")

    async def _default_cooldown(self, ctx: commands.Context[Any]) -> bool:
        command = ctx.command
        if command is None or command._buckets.valid or await self.is_owner(ctx.author):
            return True
        cfg = self.config.settings.cooldowns
        mapping = self._cooldown_maps.get(command.qualified_name)
        cooldown = mapping._cooldown if mapping is not None else None
        if cooldown is None or cooldown.rate != cfg.default_rate or cooldown.per != cfg.default_per:
            mapping = commands.CooldownMapping.from_cooldown(cfg.default_rate, cfg.default_per,
                                                             commands.BucketType.user)
            self._cooldown_maps[command.qualified_name] = mapping
        bucket = mapping.get_bucket(ctx.message)
        if bucket is not None and (retry := bucket.update_rate_limit()):
            raise commands.CommandOnCooldown(bucket, retry, commands.BucketType.user)
        return True

    def register_hook(self, event_name: str, callback: Any, priority: int = 0) -> bool:
        return self.hooks.register(event_name, callback, priority)

    def unregister_hook(self, event_name: str, callback: Any) -> bool:
        return self.hooks.unregister(event_name, callback)

    async def emit_hook(self, event_name: str, **kwargs: Any) -> int:
        return await self.hooks.emit(event_name, **kwargs)

    def list_hooks(self) -> dict[str, list[str]]:
        return {e: [getattr(h.callback, "__name__", "?") for h in hs] for e, hs in self.hooks.hooks.items()}

    def get_hook_history(self, limit: int = 20) -> list[dict[str, Any]]:
        from dataclasses import asdict

        return [asdict(h) for h in list(self.hooks.history)[-limit:]]

    def disable_hook(self, hook_id: str) -> bool:
        return self.hooks.disable(hook_id)

    def enable_hook(self, hook_id: str) -> bool:
        return self.hooks.enable(hook_id)

    async def register_plugin(self, name: str, **kwargs: Any) -> PluginMetadata | None:
        return await self.plugins.register_plugin(name, **kwargs)

    def unregister_plugin(self, name: str) -> bool:
        return self.plugins.unregister_plugin(name)

    def get_plugin_info(self, name: str) -> PluginMetadata | None:
        return self.plugins.get(name)

    def get_all_plugins(self) -> dict[str, PluginMetadata]:
        return self.plugins.all()

    def check_dependencies(self, name: str) -> tuple[bool, list[str]]:
        meta = self.plugins.get(name)
        if meta is None:
            return False, ["Plugin not registered"]
        problems = self.plugins.check_dependencies(meta)
        return not problems, problems

    def detect_conflicts(self, name: str) -> tuple[bool, list[str]]:
        meta = self.plugins.get(name)
        if meta is None:
            return False, []
        hits = self.plugins.detect_conflicts(meta)
        return bool(hits), hits

    @property
    def extension_load_times(self) -> dict[str, float]:
        return {k: v / 1000 for k, v in self.ext.load_times.items()}
