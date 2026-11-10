# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import re
import secrets
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zdbf.cogs.backup.snapshot import checksum
from zdbf.cogs.compat import LEGACY_COMMANDS
from zdbf.core.config import Config, ConfigError, Settings
from zdbf.core.database import Database, utcnow_iso

TEMPLATE_MAP: dict[str, tuple[str, dict[str, str]]] = {
    "mega_welcome": ("welcome", {"welcome_channel_id": "channel_id", "welcome_message": "message", "use_embed": "card",
                                 "embed_title": "title", "embed_color": "color", "auto_role_id": "auto_role_id",
                                 "send_dm": "send_dm", "dm_message": "dm_message"}),
    "goodbye_system": ("goodbye", {"goodbye_channel_id": "channel_id", "goodbye_message": "message",
                                   "use_embed": "card"}),
    "auto_role_on_reaction": ("reaction_roles", {"message_id": "message_id", "channel_id": "channel_id",
                                                 "role_emoji_map": "mapping",
                                                 "remove_role_on_unreact": "remove_on_unreact"}),
    "message_filter": ("automod", {"banned_words": "words", "action": "action", "timeout_duration": "timeout_seconds",
                                   "log_channel_id": "log_channel_id", "ignore_roles": "ignore_roles",
                                   "case_sensitive": "case_sensitive"}),
    "leveling_system": ("leveling", {"xp_per_message": "xp_per_message", "xp_cooldown": "cooldown",
                                     "levelup_channel_id": "levelup_channel_id", "levelup_message": "levelup_message",
                                     "role_rewards": "role_rewards"}),
    "scheduled_announcement": ("announcements", {"announcement_channel_id": "channel_id",
                                                 "announcement_message": "message", "interval_hours": "interval_hours",
                                                 "use_embed": "card"}),
    "ticket_system": ("tickets", {"ticket_category_id": "category_id", "support_role_id": "support_role_id",
                                  "ticket_name_template": "name_template"}),
    "voice_activity_tracker": ("voice_log", {"log_channel_id": "channel_id", "log_joins": "log_joins",
                                             "log_leaves": "log_leaves", "log_mutes": "log_mutes"}),
    "webhook_bridge": ("webhook_bridge", {"webhook_url": "webhook_url", "trigger_channels": "channel_ids"}),
    "dynamic_voice_channels": ("dynamic_voice", {"trigger_channel_id": "hub_channel_id", "category_id": "category_id",
                                                 "channel_name_template": "name_template", "user_limit": "user_limit"}),
}
V1_EVENTS = {"on_member_join": "member_join", "on_member_remove": "member_leave", "on_message": "message",
             "on_raw_reaction_add": "reaction_add", "on_reaction_add": "reaction_add",
             "on_voice_state_update": "voice_join", "scheduled": "schedule"}


def convert_conditions(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"logic": "and", "rules": []}
    rules: list[dict[str, Any]] = []
    for r in raw.get("rules", []):
        if not isinstance(r, dict):
            continue
        kind = r.get("type")
        if kind in ("time_range", "day_of_week"):
            rules.append(dict(r))
        elif kind == "role_hierarchy":
            comparison = r.get("comparison", "has")
            rules.append({"type": {"above": "role_above", "below": "role_below"}.get(comparison, "has_role"),
                          "role_id": int(r.get("role_id", 0))})
        elif kind == "message_count":
            rules.append({"type": "message_count", "operator": r.get("operator", ">"), "value": int(r.get("value", 0))})
        elif kind == "user_age":
            rules.append({"type": "account_age", "min_days": int(r.get("min_days", 0))})
        elif kind == "custom_variable":
            rules.append({"type": "variable", "name": r.get("variable", ""), "operator": r.get("operator", "=="),
                          "value": r.get("value", "")})
    return {"logic": "or" if str(raw.get("logic", "AND")).upper() == "OR" else "and", "rules": rules}


def convert_action(a: dict[str, Any]) -> dict[str, Any] | None:
    kind = a.get("type")
    match kind:
        case "send_message":
            embed = a.get("embed") or {}
            return {"type": "send_message", "channel_id": _int(a.get("channel_id")), "card": bool(a.get("use_embed")),
                    "message": a.get("message") or embed.get("description") or "", "title": embed.get("title"),
                    "color": str(embed.get("color", "")).lstrip("#") or None}
        case "send_dm":
            return {"type": "send_dm", "message": a.get("message", "")}
        case "add_role" | "remove_role":
            return {"type": kind, "role_id": _int(a.get("role_id"))}
        case "timeout":
            return {"type": "timeout", "seconds": int(a.get("duration", 60))}
        case "webhook":
            return {"type": "webhook", "url": a.get("url", ""), "payload": a.get("payload") or None}
        case "create_role":
            return {"type": "create_role", "name": a.get("role_name", "new role"), "color": a.get("color", "7C3AED")}
        case "delay":
            return {"type": "delay", "seconds": int(a.get("seconds", 1))}
        case "trigger_hook":
            return {"type": "trigger_automation", "hook_id": str(a.get("hook_id", ""))}
    return None


def _int(value: Any) -> int | None:
    return int(value) if str(value or "").isdigit() else None


AUTOMOD_ACTIONS = {"warn": "delete_warn", "log": "log_only", "delete": "delete", "timeout": "timeout", "kick": "kick"}
STATUS_TYPES = {"playing", "watching", "listening", "competing", "custom"}


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.warnings: list[str] = []

    def ok(self, text: str) -> None:
        self.lines.append(f"  ✓ {text}")
        print(f"  ✓ {text}")

    def warn(self, text: str) -> None:
        self.warnings.append(text)
        print(f"  ! {text}")


def _bool(v: Any) -> Any:
    if isinstance(v, str) and v.lower() in ("true", "false", "yes", "no", "1", "0", "on", "off"):
        return v.lower() in ("true", "yes", "1", "on")
    return v


def _num(v: Any) -> Any:
    if isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v.strip()):
        f = float(v)
        return int(f) if f.is_integer() else f
    return v


def _read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    raise TypeError(f"cannot write {type(v).__name__} to TOML")


def dump_toml(data: dict[str, Any]) -> str:
    out = ["# ZDBF V2 configuration - migrated from V1.",
           "# Every option is documented in zdbf/core/default_config.toml.", ""]
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        scalars = {k: v for k, v in values.items() if not (isinstance(v, list) and v and isinstance(v[0], dict))
                   and not isinstance(v, dict)}
        tables = {k: v for k, v in values.items() if isinstance(v, list) and v and isinstance(v[0], dict)}
        out.append(f"[{section}]")
        out += [f"{k} = {toml_value(v)}" for k, v in scalars.items() if v is not None]
        out.append("")
        for name, rows in tables.items():
            for row in rows:
                out.append(f"[[{section}.{name}]]")
                out += [f"{k} = {toml_value(v)}" for k, v in row.items() if v is not None]
                out.append("")
    return "\n".join(out)


def convert_weekday_field(field: str) -> str:
    if field.strip() == "*":
        return "*"
    values: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part == "*":
            rng = range(0, 7, step)
        elif "-" in part:
            a, b = part.split("-", 1)
            rng = range(int(a), int(b) + 1, step)
        else:
            rng = range(int(part), (6 if step > 1 else int(part)) + 1, step)
        values.update(rng)
    return ",".join(str(x) for x in sorted({(v + 1) % 7 for v in values}))


def convert_cron(expr: str) -> str:
    parts = expr.split()
    if len(parts) == 5:
        parts[4] = convert_weekday_field(parts[4])
    return " ".join(parts)


class Migrator:
    def __init__(self, src: Path, dest: Path, *, dry_run: bool, force: bool) -> None:
        self.src = src
        self.dest = dest
        self.dry = dry_run
        self.force = force
        self.r = Report()
        self.env = _read_env(src / ".env")
        self.v1_config: dict[str, Any] = {}
        cfg_path = src / "config.json"
        if cfg_path.exists():
            self.v1_config = json.loads(cfg_path.read_text(encoding="utf-8"))

    def build_config(self) -> dict[str, Any]:
        c, env = self.v1_config, self.env
        data = Settings().model_dump()
        bot = data["bot"]
        bot["prefix"] = c.get("prefix", "!")
        bot["mention_prefix"] = bool(c.get("allow_mention_prefix", True))
        bot["owner_ids"] = [int(x) for x in c.get("owner_ids", []) if str(x).isdigit()]
        status = c.get("status", {})
        rotation = []
        for s in status.get("statuses", []) or ([status] if status.get("text") else []):
            kind = str(s.get("type", "watching")).lower()
            presence = str(s.get("presence", "online")).lower()
            rotation.append({"presence": presence if presence in ("online", "idle", "dnd", "invisible") else "online",
                             "type": kind if kind in STATUS_TYPES else "watching", "text": str(s.get("text", ""))[:128]})
        if rotation:
            data["status"]["rotation"] = rotation
        data["status"]["interval"] = max(10, int(status.get("interval", 20)))
        log = c.get("logging", {})
        data["logging"].update(level=str(log.get("level", "INFO")).upper(),
                               max_bytes=int(log.get("max_bytes", 10485760)), backup_count=int(log.get("backup_count", 5)))
        ext = c.get("extensions", {})
        data["extensions"].update(auto_load=bool(ext.get("auto_load", True)), blacklist=list(ext.get("blacklist", [])),
                                  hot_reload=bool(c.get("auto_reload", True)))
        cd = c.get("cooldowns", {})
        data["cooldowns"].update(default_rate=int(cd.get("default_rate", 3)), default_per=float(cd.get("default_per", 5.0)))
        fw = c.get("framework", {})
        mods = data["modules"]
        for v1, v2 in (("enable_event_hooks", "eventhooks"), ("enable_plugin_registry", "plugins"),
                       ("enable_framework_diagnostics", "diagnostics"), ("enable_shard_monitor", "shards"),
                       ("enable_backup_restore", "backup")):
            if v1 in fw:
                mods[v2] = bool(fw[v1])
        mods["cluster"] = env.get("ENABLE_SHARD_MANAGER", "false").lower() == "true"
        if env.get("ENABLE_SHARD_MONITOR", "true").lower() == "false":
            mods["shards"] = False
        if env.get("ENABLE_BACKUP_RESTORE", "true").lower() == "false":
            mods["backup"] = False
        if env.get("FW_LOOP_LAG_THRESHOLD_MS", "").isdigit():
            data["diagnostics"]["loop_lag_threshold_ms"] = int(env["FW_LOOP_LAG_THRESHOLD_MS"])
        for envkey, key in (("BACKUP_MAX_PER_GUILD", "max_per_guild"), ("BACKUP_COOLDOWN", "cooldown_seconds"),
                            ("BACKUP_AUTO_INTERVAL", "auto_interval_hours"), ("BACKUP_RETENTION_DAYS", "retention_days")):
            if env.get(envkey, "").isdigit():
                data["backup"][key] = int(env[envkey])
        if env.get("SHARD_ALERT_THRESHOLD", "").isdigit():
            data["shards"]["alert_threshold"] = max(1, min(20, int(env["SHARD_ALERT_THRESHOLD"])))
        cl = data["cluster"]
        cl["mode"] = env.get("SHARD_IPC_MODE", "server").lower() if env.get("SHARD_IPC_MODE", "server").lower() in (
            "server", "client") else "server"
        cl["host"] = env.get("SHARD_IPC_HOST", cl["host"])
        cl["port"] = int(env["SHARD_IPC_PORT"]) if env.get("SHARD_IPC_PORT", "").isdigit() else cl["port"]
        cl["name"] = env.get("SHARD_CLUSTER_NAME", cl["name"])
        Settings.model_validate(data)
        return data

    def write_config(self) -> None:
        target = self.dest / "config.toml"
        data = self.build_config()
        text = dump_toml(data)
        Config.parse(text)
        if target.exists() and not self.force:
            target = self.dest / "config.migrated.toml"
            self.r.warn(f"config.toml exists - wrote {target.name} instead (use --force to overwrite)")
        if not self.dry:
            target.write_text(text, encoding="utf-8")
        self.r.ok(f"config → {target.name} (prefix {data['bot']['prefix']!r}, "
                  f"{len(data['status']['rotation'])} status entries)")

    def write_env(self) -> None:
        keep = ("DISCORD_TOKEN", "BOT_OWNER_ID", "SHARD_COUNT", "SHARD_IDS", "SHARD_IPC_SECRET", "SHARD_CLUSTER_NAME",
                "SHARD_IPC_MODE")
        lines = ["# ZDBF V2 - migrated from V1", *(f"{k}={self.env[k]}" for k in keep if self.env.get(k))]
        if self.env.get("SHARD_IPC_SECRET") == "change_me_please":
            self.r.warn("SHARD_IPC_SECRET is the V1 default - V2 refuses it; set a 16+ character secret")
        target = self.dest / ".env"
        if target.exists() and not self.force:
            target = self.dest / ".env.migrated"
            self.r.warn(f".env exists - wrote {target.name} instead")
        if not self.dry:
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            target.chmod(0o600)
        self.r.ok(f"secrets → {target.name} ({sum(1 for k in keep if self.env.get(k))} values)")

    async def migrate_data(self) -> None:
        db = Database(self.dest / "data" / "zdbf.db") if not self.dry else Database(":memory:")
        await db.connect()
        try:
            await self._guild_dbs(db)
            await self._main_db(db)
            await self._permissions(db)
            await self._backups(db)
            await self._automations(db)
            await self._settings(db)
        finally:
            await db.close()
        self._marketplace()

    async def _guild_dbs(self, db: Database) -> None:
        guilds = 0
        for path in sorted((self.src / "data").glob("*/guild.db")):
            if not path.parent.name.isdigit():
                continue
            gid = int(path.parent.name)
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "guild_settings" in tables:
                    for row in conn.execute("SELECT key, value FROM guild_settings"):
                        if row["key"] == "prefix" and row["value"]:
                            await db.set_guild_prefix(gid, row["value"])
                        elif row["key"] == "mention_prefix_enabled":
                            await db.set_guild_mention_prefix_enabled(gid, str(row["value"]) in ("1", "True", "true"))
                        else:
                            await db.set_setting(gid, f"v1.{row['key']}", row["value"])
                if "command_stats" in tables:
                    for row in conn.execute("SELECT command_name, usage_count, last_used FROM command_stats"):
                        name = LEGACY_COMMANDS.get(row[0], row[0])
                        await db.execute(
                            "INSERT INTO command_stats (guild_id, command_name, usage_count, last_used) VALUES (?, ?, ?, ?)"
                            " ON CONFLICT(guild_id, command_name) DO UPDATE SET usage_count = usage_count + excluded.usage_count",
                            (gid, name, row[1] or 0, row[2]))
                extra = tables - {"guild_settings", "command_stats", "sqlite_sequence"}
            if extra:
                target = self.dest / "data" / str(gid) / "guild.db"
                if not self.dry and not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                self.r.ok(f"guild {gid}: kept extension tables {sorted(extra)} in data/{gid}/guild.db")
            guilds += 1
        self.r.ok(f"guild settings & usage stats from {guilds} guild database(s)")

    async def _main_db(self, db: Database) -> None:
        path = self.src / "data" / "main.db"
        if not path.exists():
            self.r.warn("data/main.db not found - no scheduled tasks migrated")
            return
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            rows = list(conn.execute("SELECT * FROM scheduled_tasks")) if "scheduled_tasks" in tables else []
            extra = tables - {"scheduled_tasks", "_schema_migrations", "global_stats", "sqlite_sequence"}
        for r in rows:
            task = dict(r)
            cron = convert_cron(task["cron_expression"])
            await db.execute(
                "INSERT OR REPLACE INTO scheduled_tasks (task_id, guild_id, channel_id, creator_id, task_name, task_type,"
                " cron_expression, payload, enabled, last_run, next_run, run_count, max_runs, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                (task["task_id"], task["guild_id"], task["channel_id"], task["creator_id"], task["task_name"],
                 task["task_type"], cron, task["payload"], task["enabled"], task["last_run"], task["run_count"],
                 task["max_runs"], task["created_at"], utcnow_iso()))
        self.r.ok(f"{len(rows)} scheduled task(s) (weekday numbers converted to standard cron)")
        if extra:
            self.r.warn(f"main.db has extension tables {sorted(extra)} - copied to data/v1_main.db for reference")
            if not self.dry:
                shutil.copy2(path, self.dest / "data" / "v1_main.db")

    async def _permissions(self, db: Database) -> None:
        perms = self.v1_config.get("command_permissions") or {}
        if not perms:
            return
        mapped = {LEGACY_COMMANDS.get(cmd, cmd): [int(r) for r in roles if str(r).isdigit()] for cmd, roles in perms.items()}
        await db.kv_set("migration.v1_command_permissions", mapped)
        self.r.ok(f"{len(mapped)} command restriction(s) queued (assigned to the right servers on first start)")

    async def _backups(self, db: Database) -> None:
        root = self.src / "data" / "backups"
        count = 0
        for index in sorted(root.glob("*/index.json")) if root.exists() else []:
            gid = int(index.parent.name) if index.parent.name.isdigit() else None
            if gid is None:
                continue
            for e in json.loads(index.read_text(encoding="utf-8")):
                snap_path = index.parent / f"{e['id']}.json"
                if not snap_path.exists():
                    self.r.warn(f"backup {e['id']} of guild {gid}: snapshot file missing")
                    continue
                snap = json.loads(snap_path.read_text(encoding="utf-8"))
                self._upgrade_snapshot(snap)
                target = self.dest / "data" / "backups" / str(gid) / f"{e['id']}.json.gz"
                raw = json.dumps(snap, default=str, separators=(",", ":")).encode()
                if not self.dry:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(gzip.compress(raw))
                counts = {"roles": e.get("roles_count", 0), "categories": e.get("categories_count", 0),
                          "channels": sum(e.get(k, 0) for k in ("text_channels_count", "voice_channels_count",
                                                                 "forum_channels_count", "stage_channels_count")),
                          "emojis": e.get("emojis_count", 0), "stickers": e.get("stickers_count", 0),
                          "members": e.get("member_roles_count", 0)}
                await db.execute(
                    "INSERT OR REPLACE INTO backups (backup_id, guild_id, label, note, pinned, automatic, created_by,"
                    " created_at, size_bytes, checksum, version, components, counts, file)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (e["id"], gid, e.get("label", "V1 backup")[:100], e.get("notes") or None, int(bool(e.get("pinned"))),
                     int(bool(e.get("auto_backup"))), int(e.get("author_id") or 0), e.get("timestamp", utcnow_iso()),
                     len(gzip.compress(raw)) if self.dry else target.stat().st_size, checksum(snap),
                     str(snap.get("version", "2.2.0")), "[]", json.dumps(counts),
                     target.relative_to(self.dest).as_posix()))
                count += 1
        self.r.ok(f"{count} backup(s) imported")

    @staticmethod
    def _upgrade_snapshot(snap: dict[str, Any]) -> None:
        s = snap.get("server_settings") or {}
        channels = {c["id"]: c["name"] for k in ("text_channels", "voice_channels") for c in snap.get(k, [])}
        for v1, v2 in (("afk_channel_id", "afk_channel"), ("system_channel_id", "system_channel"),
                       ("rules_channel_id", "rules_channel"), ("public_updates_channel_id", "public_updates_channel")):
            if v1 in s and v2 not in s:
                s[v2] = channels.get(s[v1])

    async def _automations(self, db: Database) -> None:
        path = self.src / "data" / "event_hooks_creater.json"
        if not path.exists():
            return
        hooks = json.loads(path.read_text(encoding="utf-8"))
        imported = 0
        id_map: dict[str, str] = {}
        chained: list[str] = []
        for h in hooks:
            new_id = secrets.token_hex(4)
            id_map[str(h.get("hook_id"))] = new_id
            conditions = convert_conditions(h.get("conditions"))
            if isinstance(h.get("actions"), list) and h["actions"]:
                actions = [c for c in (convert_action(a) for a in h["actions"] if isinstance(a, dict)) if c]
                trigger = V1_EVENTS.get(str(h.get("event", "")), "message")
                config: dict[str, Any] = {"trigger": trigger, "match": "any", "actions": actions[:15]}
                if trigger == "schedule":
                    config["interval_minutes"] = int(h.get("params", {}).get("interval_minutes", 60))
                if any(a["type"] == "trigger_automation" for a in actions):
                    chained.append(new_id)
                await db.execute(
                    "INSERT INTO automations (hook_id, guild_id, name, template, config, conditions, enabled, "
                    "created_by, created_at, updated_at, run_count, error_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id, int(h["guild_id"]), str(h.get("template_name") or h.get("name") or "Custom automation")[:80],
                     "custom", json.dumps(config), json.dumps(conditions), int(bool(h.get("enabled", True))),
                     int(h["created_by"]) if str(h.get("created_by", "")).isdigit() else 0,
                     h.get("created_at", utcnow_iso()), utcnow_iso(), int(h.get("execution_count", 0)),
                     int(h.get("error_count", 0))))
                imported += 1
                if len(h["actions"]) != len(actions):
                    self.r.warn(f"automation {h.get('hook_id')}: {len(h['actions']) - len(actions)} unknown action(s) "
                                "dropped")
                continue
            mapping = TEMPLATE_MAP.get(h.get("template_id", ""))
            if mapping is None:
                self.r.warn(f"automation {h.get('hook_id')}: unknown V1 template {h.get('template_id')!r} skipped")
                continue
            template, fields = mapping
            params = h.get("params", {})
            config = {new: _num(_bool(params[old])) for old, new in fields.items() if old in params}
            enabled = bool(h.get("enabled", True))
            note = None
            if template == "automod":
                config["action"] = AUTOMOD_ACTIONS.get(str(config.get("action", "delete")), "delete")
                if isinstance(config.get("ignore_roles"), str):
                    config["ignore_roles"] = [int(x) for x in re.findall(r"\d{15,21}", config["ignore_roles"])]
            if template == "webhook_bridge":
                config["events"] = "message"
            if template == "tickets":
                enabled, note = False, "V1 tickets used reactions - set a panel channel with /hooks info → Edit"
            for key in ("mapping", "role_rewards"):
                if isinstance(config.get(key), dict):
                    config[key] = json.dumps(config[key])
            await db.execute(
                "INSERT INTO automations (hook_id, guild_id, name, template, config, conditions, enabled, created_by,"
                " created_at, updated_at, run_count, error_count, last_error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id, int(h["guild_id"]), h.get("template_name", template)[:80], template,
                 json.dumps(config), json.dumps(conditions), int(enabled),
                 int(h["created_by"]) if str(h.get("created_by", "")).isdigit() else 0, h.get("created_at", utcnow_iso()),
                 utcnow_iso(), int(h.get("execution_count", 0)), int(h.get("error_count", 0)), note))
            imported += 1
            if note:
                self.r.warn(f"automation '{h.get('template_name')}' (guild {h['guild_id']}): {note}")
        for hook_id in chained:
            raw = await db.fetchval("SELECT config FROM automations WHERE hook_id = ?", (hook_id,))
            config = json.loads(raw)
            for a in config["actions"]:
                if a["type"] == "trigger_automation":
                    a["hook_id"] = id_map.get(a["hook_id"], a["hook_id"])
            await db.execute("UPDATE automations SET config = ? WHERE hook_id = ?", (json.dumps(config), hook_id))
        self.r.ok(f"{imported} automation(s) imported")

    async def _settings(self, db: Database) -> None:
        channels: dict[str, int] = {}
        for file, system in (("event_hooks_config.json", "eventhooks"), ("framework_diagnostics_config.json", "diagnostics"),
                             ("plugin_registry_config.json", "plugins"), ("shard_monitor/config.json", "shards")):
            p = self.src / "data" / file
            if p.exists():
                cfg = json.loads(p.read_text(encoding="utf-8"))
                if cfg.get("alert_channel_id"):
                    channels[system] = int(cfg["alert_channel_id"])
                if system == "plugins":
                    await db.kv_set("plugins.settings", {"enforce_dependencies": cfg.get("enforce_dependencies", True),
                                                         "enforce_conflicts": cfg.get("enforce_conflicts", True)})
        if channels:
            await db.kv_set("alerts.channels", channels)
            self.r.ok(f"alert channels: {', '.join(channels)}")

    def _marketplace(self) -> None:
        src = self.src / "data" / "marketplace"
        dest = self.dest / "data" / "marketplace"
        moved = []
        for name in ("ZygnalID.txt", "license_accepted.json"):
            if (src / name).exists():
                if not self.dry:
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src / name, dest / name)
                moved.append(name)
        if moved:
            self.r.ok(f"marketplace: {', '.join(moved)} (ZygnalID becomes your ZSync ZDBF Key on first start)")


async def run(args: argparse.Namespace) -> int:
    src = Path(args.source).expanduser().resolve()
    dest = Path(args.dest).resolve()
    if not (src / "main.py").exists() and not (src / "config.json").exists():
        print(f"✗ {src} does not look like a ZDBF V1 installation (no main.py / config.json)")
        return 2
    if (dest / "data" / "zdbf.db").exists() and not args.force and not args.dry_run:
        print("✗ data/zdbf.db already exists - V2 has run here before. Use --force to merge into it.")
        return 2
    print(f"Migrating {src} → {dest}{' (dry run)' if args.dry_run else ''}\n")
    m = Migrator(src, dest, dry_run=args.dry_run, force=args.force)
    try:
        m.write_config()
    except (ConfigError, ValueError) as exc:
        m.r.warn(f"config could not be converted: {exc}")
    m.write_env()
    await m.migrate_data()
    print(f"\nDone - {len(m.r.lines)} step(s), {len(m.r.warnings)} warning(s).")
    if not args.dry_run:
        print("Next: review config.toml, then start the bot with  python -m zdbf")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="path to the V1 installation")
    parser.add_argument("--dest", default=".", help="V2 directory (default: current directory)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be migrated without writing")
    parser.add_argument("--force", action="store_true", help="overwrite config.toml/.env and merge into an existing DB")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
