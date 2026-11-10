# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

CORE_MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "initial",
        """
        CREATE TABLE IF NOT EXISTS global_kv (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id   INTEGER NOT NULL,
            key        TEXT    NOT NULL,
            value      TEXT,
            updated_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, key)
        );

        CREATE TABLE IF NOT EXISTS command_permissions (
            guild_id INTEGER NOT NULL,
            command  TEXT    NOT NULL,
            role_id  INTEGER NOT NULL,
            PRIMARY KEY (guild_id, command, role_id)
        );

        CREATE TABLE IF NOT EXISTS command_stats (
            guild_id     INTEGER NOT NULL DEFAULT 0,
            command_name TEXT    NOT NULL,
            usage_count  INTEGER NOT NULL DEFAULT 0,
            last_used    TEXT,
            PRIMARY KEY (guild_id, command_name)
        );

        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            task_id         TEXT PRIMARY KEY,
            guild_id        INTEGER,
            channel_id      INTEGER,
            creator_id      INTEGER NOT NULL,
            task_name       TEXT    NOT NULL,
            task_type       TEXT    NOT NULL DEFAULT 'message',
            cron_expression TEXT    NOT NULL,
            payload         TEXT    NOT NULL DEFAULT '{}',
            enabled         INTEGER NOT NULL DEFAULT 1,
            last_run        TEXT,
            next_run        TEXT,
            run_count       INTEGER NOT NULL DEFAULT 0,
            max_runs        INTEGER,
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run ON scheduled_tasks(next_run) WHERE enabled = 1;
        CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_guild ON scheduled_tasks(guild_id);

        CREATE TABLE IF NOT EXISTS automations (
            hook_id     TEXT PRIMARY KEY,
            guild_id    INTEGER NOT NULL,
            name        TEXT    NOT NULL,
            template    TEXT    NOT NULL,
            config      TEXT    NOT NULL DEFAULT '{}',
            conditions  TEXT    NOT NULL DEFAULT '[]',
            enabled     INTEGER NOT NULL DEFAULT 1,
            created_by  INTEGER NOT NULL,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            run_count   INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            last_run    TEXT,
            last_error  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_automations_guild ON automations(guild_id);

        CREATE TABLE IF NOT EXISTS automation_state (
            hook_id  TEXT    NOT NULL,
            scope_id INTEGER NOT NULL DEFAULT 0,
            key      TEXT    NOT NULL,
            value    TEXT,
            PRIMARY KEY (hook_id, scope_id, key)
        );
        """,
    ),
    (
        2,
        "backups",
        """
        CREATE TABLE IF NOT EXISTS backups (
            backup_id   TEXT PRIMARY KEY,
            guild_id    INTEGER NOT NULL,
            label       TEXT    NOT NULL,
            note        TEXT,
            pinned      INTEGER NOT NULL DEFAULT 0,
            automatic   INTEGER NOT NULL DEFAULT 0,
            created_by  INTEGER NOT NULL,
            created_at  TEXT    NOT NULL,
            size_bytes  INTEGER NOT NULL DEFAULT 0,
            checksum    TEXT    NOT NULL,
            version     TEXT    NOT NULL,
            components  TEXT    NOT NULL DEFAULT '[]',
            counts      TEXT    NOT NULL DEFAULT '{}',
            file        TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_backups_guild ON backups(guild_id, created_at);

        CREATE TABLE IF NOT EXISTS backup_audit (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id   INTEGER NOT NULL,
            action     TEXT    NOT NULL,
            user_id    INTEGER NOT NULL,
            backup_id  TEXT,
            details    TEXT,
            created_at TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_backup_audit_guild ON backup_audit(guild_id, created_at);
        """,
    ),
    (
        3,
        "automation_runs",
        """
        CREATE TABLE IF NOT EXISTS automation_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            hook_id     TEXT    NOT NULL,
            guild_id    INTEGER NOT NULL,
            at          TEXT    NOT NULL,
            event       TEXT    NOT NULL,
            ok          INTEGER NOT NULL,
            user_id     INTEGER,
            channel_id  INTEGER,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            error       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_automation_runs_hook ON automation_runs(hook_id, id);
        """,
    ),
]
