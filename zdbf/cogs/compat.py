# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot

log = logging.getLogger("zdbf.compat")

LEGACY_COMMANDS: dict[str, str] = {
    "shardinfo": "stats shards",
    "cleanup": "fw cleanup",
    "cachestats": "fw cache",
    "atomictest": "fw atomic-test",
    "atomic_test": "fw atomic-test",
    "atomic_test_main": "fw atomic-test",
    "atomicstats": "fw cache",
    "atomic_stats": "fw cache",
    "sync": "fw sync",
    "dbstats": "fw db",
    "integritycheck": "fw integrity",
    "reload": "ext reload",
    "load": "ext load",
    "unload": "ext unload",
    "extensions": "ext list",
    "setprefix": "settings prefix",
    "config": "settings permissions",
    "mentionprefix": "settings mentionprefix",
    "serversettings": "settings view",
    "fw_diagnostics": "diag overview",
    "fw_alert_channel": "diag alerts",
    "fw_history": "diag history",
    "fw_errors": "diag errors",
    "fw_migrations": "diag migrations",
    "fw_migrate": "diag migrate",
    "fw_config_validate": "fw config validate",
    "fw_config_schema": "fw config schema",
    "slashlimit": "diag commands",
    "eh_list": "eventhooks list",
    "eh_history": "eventhooks history",
    "eh_disable": "eventhooks disable",
    "eh_enable": "eventhooks enable",
    "eh_alert_channel": "eventhooks alerts",
    "eh_reset_circuit": "eventhooks reset",
    "pr_list": "plugins list",
    "pr_info": "plugins info",
    "pr_validate": "plugins validate",
    "pr_enforce": "plugins enforce",
    "pr_alert_channel": "plugins alerts",
    "backupcreate": "backup create",
    "backuprestore": "backup restore",
    "backupview": "backup view",
    "backupdelete": "backup delete",
    "backuplist": "backup list",
    "backuppin": "backup pin",
    "backupnote": "backup note",
    "backupverify": "backup verify",
    "backupschedule": "backup schedule",
    "backupdiff": "backup diff",
    "backupexport": "backup export",
    "backupstats": "backup stats",
    "shardmonitor": "shard monitor",
    "sharddetails": "shard details",
    "shardhealth": "shard health",
    "shardalerts": "shard alerts",
    "shardreset": "shard reset",
    "clusters": "cluster status",
    "ipcstatus": "cluster ipc",
    "broadcastmsg": "cluster broadcast",
}


class Compat(commands.Cog, name="Compatibility"):
    """Keeps V1 command names working as prefix aliases."""

    def __init__(self, bot: ZDBFBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.refresh()
        self.bot.add_listener(self._on_change, "on_zdbf_extensions_changed")

    async def cog_unload(self) -> None:
        self.bot.legacy_aliases = {}

    def refresh(self) -> None:
        aliases: dict[str, str] = {}
        for old, new in LEGACY_COMMANDS.items():
            if self.bot.get_command(old) is None and self.bot.get_command(new) is not None:
                aliases[old] = new
        self.bot.legacy_aliases = aliases

    async def _on_change(self) -> None:
        self.refresh()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.refresh()
        await self._apply_migrated_permissions()

    async def _apply_migrated_permissions(self) -> None:
        pending: dict[str, list[int]] = await self.bot.db.kv_get("migration.v1_command_permissions", {})
        if not pending:
            return
        applied = 0
        for command, role_ids in pending.items():
            for role_id in role_ids:
                guild = next((g for g in self.bot.guilds if g.get_role(role_id)), None)
                if guild is not None:
                    await self.bot.db.add_command_role(guild.id, command, role_id)
                    self.bot.invalidate_permissions(guild.id)
                    applied += 1
        await self.bot.db.kv_delete("migration.v1_command_permissions")
        log.info("applied %d migrated V1 command restriction(s)", applied)


async def setup(bot: ZDBFBot) -> None:
    await bot.add_cog(Compat(bot))
