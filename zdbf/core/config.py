# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import copy
import os
import shutil
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .storage import global_file_handler

__all__ = ["Config", "ConfigError", "Secrets", "Settings"]

DEFAULT_CONFIG_PATH = Path("config.toml")
OVERRIDES_PATH = Path("data/config_overrides.json")


class ConfigError(RuntimeError):
    pass


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class BotSettings(_Section):
    prefix: str = Field("!", min_length=1, max_length=10)
    mention_prefix: bool = True
    owner_ids: list[int] = []
    dev_guild_ids: list[int] = []
    sync_on_start: bool = True
    delete_invoking_message: bool = False
    privileged_intents: list[Literal["members", "message_content", "presences"]] = ["members", "message_content"]


class StatusEntry(_Section):
    presence: Literal["online", "idle", "dnd", "invisible"] = "online"
    type: Literal["playing", "watching", "listening", "competing", "custom"] = "watching"
    text: str = Field("{guilds} servers", max_length=128)


class StatusSettings(_Section):
    interval: int = Field(20, ge=10, le=3600)
    rotation: list[StatusEntry] = [StatusEntry()]


class UISettings(_Section):
    decorative_emoji: bool = False
    help_banner: str = ""
    support_url: str = ""
    invite_button: bool = True
    invite_permissions: int = Field(8, ge=0)


class MaintenanceSettings(_Section):
    clean_pycache: bool = True
    db_backup_keep: int = Field(7, ge=1, le=100)
    db_backup_interval_hours: int = Field(24, ge=1, le=720)


class DatabaseSettings(_Section):
    path: str = "./data/zdbf.db"


class LoggingSettings(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    directory: str = "./logs"
    max_bytes: int = Field(10 * 1024 * 1024, ge=1024)
    backup_count: int = Field(5, ge=0, le=100)
    retention_days: int = Field(30, ge=0)

    @field_validator("level", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return v.upper() if isinstance(v, str) else v


class ExtensionSettings(_Section):
    directory: str = "./extensions"
    auto_load: bool = True
    hot_reload: bool = True
    hot_reload_interval: float = Field(5, ge=1, le=600)
    blacklist: list[str] = []


class CooldownSettings(_Section):
    default_rate: int = Field(3, ge=1)
    default_per: float = Field(5.0, gt=0)


class ModuleSettings(_Section):
    core: bool = True
    admin: bool = True
    settings: bool = True
    diagnostics: bool = True
    eventhooks: bool = True
    automations: bool = True
    plugins: bool = True
    scheduler: bool = True
    backup: bool = True
    shards: bool = True
    cluster: bool = False
    marketplace: bool = True
    dashboard: bool = False


class DiagnosticsSettings(_Section):
    loop_lag_threshold_ms: int = Field(500, ge=10)
    health_interval_minutes: int = Field(5, ge=1, le=1440)
    error_rate_warn_percent: float = Field(10.0, ge=0, le=100)


class BackupSettings(_Section):
    max_per_guild: int = Field(25, ge=1, le=500)
    cooldown_seconds: int = Field(300, ge=0)
    auto_interval_hours: int = Field(0, ge=0)
    retention_days: int = Field(0, ge=0)


class SchedulerSettings(_Section):
    timezone: str = "UTC"
    max_tasks_per_guild: int = Field(25, ge=1, le=500)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {v!r}") from exc
        return v


class ShardSettings(_Section):
    alert_threshold: int = Field(3, ge=1, le=20)


class ClusterSettings(_Section):
    mode: Literal["server", "client"] = "server"
    host: str = "127.0.0.1"
    port: int = Field(20000, ge=1, le=65535)
    name: str = "cluster-0"


class MarketplaceSettings(_Section):
    api_url: str = "https://zsync.eu/extension/api/extensions.php?action=list"
    download_url: str = "https://zsync.eu/extension/download.php"
    cache_minutes: int = Field(10, ge=1)
    auto_install_packages: bool = True


class DashboardSettings(_Section):
    capabilities: list[str] = [
        "view", "logs", "chat.read", "chat.send", "commands.run", "extensions", "files.read",
        "automations", "scheduler", "settings", "backups", "presence",
    ]
    approval: list[str] = [
        "files.write", "config", "marketplace", "commands.owner", "backups.restore", "guilds.leave", "system",
    ]
    approval_timeout: int = Field(300, ge=30, le=3600)
    file_roots: list[str] = ["extensions"]
    max_file_kb: int = Field(1024, ge=1, le=65536)
    idle_interval: int = Field(45, ge=15, le=600)
    locked: bool = False

    @field_validator("capabilities", "approval")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        from ..cogs.dashboard.capabilities import NAMES

        unknown = sorted(set(v) - NAMES)
        if unknown:
            raise ValueError(f"unknown dashboard capability: {', '.join(unknown)}")
        return sorted(set(v), key=v.index)

    @field_validator("file_roots")
    @classmethod
    def _roots(cls, v: list[str]) -> list[str]:
        for root in v:
            if not root.strip() or Path(root).is_absolute() or ".." in Path(root).parts:
                raise ValueError(f"file root {root!r} must be a relative folder inside the bot directory")
        return v


class Settings(BaseModel):
    model_config = ConfigDict(extra="allow")

    bot: BotSettings = BotSettings()
    status: StatusSettings = StatusSettings()
    ui: UISettings = UISettings()
    maintenance: MaintenanceSettings = MaintenanceSettings()
    database: DatabaseSettings = DatabaseSettings()
    logging: LoggingSettings = LoggingSettings()
    extensions: ExtensionSettings = ExtensionSettings()
    cooldowns: CooldownSettings = CooldownSettings()
    modules: ModuleSettings = ModuleSettings()
    diagnostics: DiagnosticsSettings = DiagnosticsSettings()
    backup: BackupSettings = BackupSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    shards: ShardSettings = ShardSettings()
    cluster: ClusterSettings = ClusterSettings()
    marketplace: MarketplaceSettings = MarketplaceSettings()
    dashboard: DashboardSettings = DashboardSettings()


class Secrets(BaseModel):
    token: str = ""
    owner_ids: list[int] = []
    shard_count: int | None = None
    shard_ids: list[int] | None = None
    ipc_secret: str = ""

    @classmethod
    def from_env(cls) -> Secrets:
        def ints(name: str) -> list[int]:
            raw = os.getenv(name, "")
            return [int(p) for p in raw.replace(" ", "").split(",") if p.strip().isdigit()]

        count = os.getenv("SHARD_COUNT", "").strip()
        shard_ids = ints("SHARD_IDS")
        return cls(
            token=os.getenv("DISCORD_TOKEN", "").strip(),
            owner_ids=ints("BOT_OWNER_ID") + ints("BOT_OWNER_IDS"),
            shard_count=int(count) if count.isdigit() and int(count) > 0 else None,
            shard_ids=shard_ids or None,
            ipc_secret=os.getenv("SHARD_IPC_SECRET", ""),
        )


_LEGACY_KEYS: dict[str, str] = {
    "prefix": "bot.prefix",
    "allow_mention_prefix": "bot.mention_prefix",
    "owner_ids": "bot.owner_ids",
    "auto_reload": "extensions.hot_reload",
    "database.path": "database.path",
    "logging.level": "logging.level",
    "extensions.auto_load": "extensions.auto_load",
    "extensions.blacklist": "extensions.blacklist",
    "cooldowns.default_rate": "cooldowns.default_rate",
    "cooldowns.default_per": "cooldowns.default_per",
}
_SENTINEL = object()


def format_validation_error(exc: ValidationError) -> list[str]:
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"{loc}: {err['msg']}")
    return lines


def _dig(data: Any, dotted: str) -> Any:
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _SENTINEL
    return cur


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _set_dotted(data: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = data
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = cur[p] = {}
        cur = nxt
    cur[parts[-1]] = value


class Config:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.getenv("ZDBF_CONFIG") or DEFAULT_CONFIG_PATH)
        self.overrides_path = OVERRIDES_PATH
        self.secrets = Secrets.from_env()
        self._file_data: dict[str, Any] = {}
        self._overrides: dict[str, Any] = {}
        self.raw: dict[str, Any] = {}
        self.settings = Settings()
        self.file_handler = global_file_handler

    @staticmethod
    def default_template() -> str:
        return resources.files("zdbf.core").joinpath("default_config.toml").read_text(encoding="utf-8")

    def ensure_exists(self) -> bool:
        if self.path.exists():
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with resources.as_file(resources.files("zdbf.core").joinpath("default_config.toml")) as src:
            shutil.copyfile(src, self.path)
        return True

    @staticmethod
    def parse(text: str) -> tuple[Settings, dict[str, Any]]:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"config.toml is not valid TOML: {exc}") from exc
        try:
            return Settings.model_validate(data), data
        except ValidationError as exc:
            raise ConfigError("Invalid config:\n  " + "\n  ".join(format_validation_error(exc))) from exc

    def load(self) -> Config:
        self.ensure_exists()
        _, self._file_data = self.parse(self.path.read_text(encoding="utf-8"))
        self._overrides = self._read_overrides()
        self._rebuild()
        return self

    def reload(self) -> Config:
        self.secrets = Secrets.from_env()
        return self.load()

    def _read_overrides(self) -> dict[str, Any]:
        import json

        try:
            return json.loads(self.overrides_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    def _rebuild(self) -> None:
        merged = _deep_merge(self._file_data, self._overrides)
        try:
            self.settings = Settings.model_validate(merged)
        except ValidationError as exc:
            raise ConfigError("Invalid config override:\n  " + "\n  ".join(format_validation_error(exc))) from exc
        self.raw = self.settings.model_dump()
        for k, v in merged.items():
            self.raw.setdefault(k, v)

    @property
    def owner_ids(self) -> set[int]:
        return set(self.settings.bot.owner_ids) | set(self.secrets.owner_ids)

    def module_enabled(self, name: str) -> bool:
        return bool(getattr(self.settings.modules, name, True))

    def get(self, key: str, default: Any = None) -> Any:
        for candidate in (key, _LEGACY_KEYS.get(key)):
            if candidate is None:
                continue
            value = _dig(self.raw, candidate)
            if value is not _SENTINEL:
                return value
        return default

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, _SENTINEL)
        if value is _SENTINEL:
            raise KeyError(key)
        return value

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self.get(key, _SENTINEL) is not _SENTINEL

    async def set(self, key: str, value: Any) -> None:
        key = _LEGACY_KEYS.get(key, key)
        previous = copy.deepcopy(self._overrides)
        _set_dotted(self._overrides, key, value)
        try:
            self._rebuild()
        except ConfigError:
            self._overrides = previous
            self._rebuild()
            raise
        await global_file_handler.atomic_write_json(self.overrides_path, self._overrides)

    async def unset(self, key: str) -> bool:
        key = _LEGACY_KEYS.get(key, key)
        parts = key.split(".")
        cur: Any = self._overrides
        for p in parts[:-1]:
            cur = cur.get(p) if isinstance(cur, dict) else None
        if not isinstance(cur, dict) or parts[-1] not in cur:
            return False
        del cur[parts[-1]]
        self._rebuild()
        await global_file_handler.atomic_write_json(self.overrides_path, self._overrides)
        return True

    @property
    def overrides(self) -> dict[str, Any]:
        return copy.deepcopy(self._overrides)

    async def initialize(self) -> None:
        self.load()

    async def save(self, data: dict[str, Any] | None = None) -> None:
        if data:
            for k, v in data.items():
                await self.set(k, v)
