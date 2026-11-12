# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["BY_NAME", "CATALOGUE", "NAMES", "READ_ONLY", "Capability", "Policy"]


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    label: str
    description: str
    dangerous: bool = False


CATALOGUE: tuple[Capability, ...] = (
    Capability("view", "View", "Status, statistics and lists"),
    Capability("logs", "Logs", "Live log tail"),
    Capability("chat.read", "Read chat", "Read channels the bot can see"),
    Capability("chat.send", "Send chat", "Send, edit and delete the bot's own messages, react"),
    Capability("chat.moderate", "Moderate chat", "Delete other members' messages, pin"),
    Capability("commands.run", "Run commands", "Run commands with the rights of an ordinary member"),
    Capability("commands.owner", "Run owner commands", "Run commands with the rights of the bot owner", True),
    Capability("extensions", "Extensions", "Load, unload and reload extensions"),
    Capability("marketplace", "Marketplace", "Install extensions and Python packages", True),
    Capability("files.read", "Read files", "Read files inside the allowed folders"),
    Capability("files.write", "Write files", "Create, change, rename and delete files", True),
    Capability("config", "Configuration", "Change config.toml and runtime overrides", True),
    Capability("automations", "Automations", "Manage server automations"),
    Capability("scheduler", "Scheduler", "Manage scheduled tasks"),
    Capability("settings", "Server settings", "Prefixes and command permissions"),
    Capability("backups", "Backups", "Create, list and compare backups"),
    Capability("backups.restore", "Restore backups", "Restore a server from a backup", True),
    Capability("presence", "Presence", "Change the bot's status"),
    Capability("database", "Database", "Read-only database browser"),
    Capability("guilds.leave", "Leave servers", "Make the bot leave a server", True),
    Capability("system", "System", "Shut the bot down", True),
)
BY_NAME: dict[str, Capability] = {c.name: c for c in CATALOGUE}
NAMES: frozenset[str] = frozenset(BY_NAME)
READ_ONLY: frozenset[str] = frozenset({"view", "logs", "chat.read", "files.read", "database"})


class Policy:
    def __init__(self, settings: Any) -> None:
        self.enabled: frozenset[str] = frozenset(settings.capabilities) & NAMES
        self.approval: frozenset[str] = frozenset(settings.approval) & NAMES
        self.locked: bool = bool(settings.locked)

    def allows(self, capability: str) -> bool:
        if capability not in self.enabled:
            return False
        return not self.locked or capability in READ_ONLY

    def needs_approval(self, capability: str) -> bool:
        return capability in self.approval

    def describe(self) -> list[dict[str, Any]]:
        return [
            {"name": c.name, "label": c.label, "description": c.description, "dangerous": c.dangerous,
             "enabled": c.name in self.enabled, "active": self.allows(c.name),
             "approval": c.name in self.approval}
            for c in CATALOGUE
        ]
