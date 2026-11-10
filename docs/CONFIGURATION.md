# Configuration

ZDBF V2 reads three sources:

| Source | For | Edited by |
|---|---|---|
| `config.toml` | everything an operator sets by hand | you (created with defaults on first start) |
| `.env` | secrets and per-process values | you |
| `data/config_overrides.json` | changes made at runtime (`/fw config set`, `/fw modules`, `/shard alerts`) | the bot |

Overrides are layered on top of `config.toml`, so your file and its comments are
never rewritten. Remove an override with `/fw config unset <key>`.

```bash
python -m zdbf --check          # validate config.toml + .env and exit
```

In Discord: `/fw config validate`, `/fw config show [section]`, `/fw config schema`,
`/fw config reload` (re-reads both files without a restart - intents, sharding and the
database path still need one).

## `.env`

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN` | **required** - the bot token |
| `BOT_OWNER_ID` | extra owner IDs, comma separated (the application owner/team is detected automatically) |
| `ZDBF_CONFIG` | alternative path to `config.toml` |
| `SHARD_COUNT`, `SHARD_IDS` | sharding for this process (leave empty for automatic sharding) |
| `SHARD_IPC_SECRET` | cluster secret (16+ characters, identical on all clusters) |
| `SHARD_CLUSTER_NAME`, `SHARD_IPC_MODE`, `SHARD_IPC_HOST`, `SHARD_IPC_PORT` | per-process overrides of `[cluster]` |

## `config.toml` reference

This is the default file, with every option and its explanation:

```toml
# ═══════════════════════════════════════════════════════════════════
#  ZDBF V2 — configuration
#  Secrets (token, IPC secret) go in .env, everything else lives here.
#  Validate any time with  /fw config validate
# ═══════════════════════════════════════════════════════════════════

[bot]
prefix = "!"
mention_prefix = true          # allow @Bot <command>
owner_ids = []                 # extra owners; app owner / team members are detected automatically
# Owner-only command groups (/fw, /ext, /shard ...) are synced only to these
# guilds. Leave empty to sync them globally (they stay owner-locked either way).
dev_guild_ids = []
sync_on_start = true           # sync slash commands on startup (only when they changed)
delete_invoking_message = false
# Privileged intents (enable them in the Developer Portal -> Bot as well).
# "members" is needed for backups/automations, "message_content" for prefix commands.
privileged_intents = ["members", "message_content"]

[status]
interval = 20                  # seconds between rotations
# Placeholders: {guilds} {users} {shards} {commands} {prefix} {version}
[[status.rotation]]
presence = "online"            # online | idle | dnd | invisible
type = "watching"              # playing | watching | listening | competing | custom
text = "{guilds} servers"

[[status.rotation]]
presence = "online"
type = "custom"
text = "Powered by ZDBF V2 👑"

[ui]
decorative_emoji = false       # true = show emoji in card titles (status dots are always shown)
help_banner = ""               # image URL shown on top of /help (empty = the bot's profile banner, if any)
support_url = ""               # adds a "Support server" button to /help and /about
invite_button = true           # "Invite" button on /help for public bots
invite_permissions = 8         # permissions integer for the invite link (8 = Administrator)

[maintenance]
clean_pycache = true           # hourly __pycache__ cleanup of extensions/
db_backup_keep = 7             # rolling database backups in data/db_backups/
db_backup_interval_hours = 24

[database]
path = "./data/zdbf.db"

[logging]
level = "INFO"                 # DEBUG | INFO | WARNING | ERROR
directory = "./logs"
max_bytes = 10485760
backup_count = 5
retention_days = 30

[extensions]
directory = "./extensions"
auto_load = true
hot_reload = true              # reload extensions when their files change
hot_reload_interval = 5        # seconds
blacklist = []                 # extension names that never auto-load

[cooldowns]
default_rate = 3               # commands without their own cooldown: 3 uses ...
default_per = 5.0              # ... per 5 seconds, per user (bot owners are exempt)

# Turn built-in modules on or off.
[modules]
core = true
admin = true
settings = true
diagnostics = true
eventhooks = true
automations = true
plugins = true
scheduler = true
backup = true
shards = true
cluster = false                # multi-process IPC, see [cluster]
marketplace = true

[diagnostics]
loop_lag_threshold_ms = 500
health_interval_minutes = 5
error_rate_warn_percent = 10.0

[backup]
max_per_guild = 25
cooldown_seconds = 300
auto_interval_hours = 0        # 0 = disabled
retention_days = 0             # 0 = keep forever (pinned backups are always kept)

[scheduler]
timezone = "UTC"               # IANA name, e.g. "Europe/Berlin" - cron times use this zone
max_tasks_per_guild = 25

[shards]
alert_threshold = 3            # consecutive failures before alerting

[cluster]
mode = "server"                # server | client
host = "127.0.0.1"
port = 20000
name = "cluster-0"
# secret: set SHARD_IPC_SECRET in .env

[marketplace]
api_url = "https://zsync.eu/extension/api/extensions.php?action=list"
download_url = "https://zsync.eu/extension/download.php"
cache_minutes = 10
```

Extensions can add their own top-level tables - see [EXTENSIONS.md](EXTENSIONS.md#configuration).

## Database safety

* Writes go through one connection and are committed atomically; reads use a second,
  read-only connection that only ever sees committed data.
* On start the database is checked (`PRAGMA quick_check`). A damaged file is moved aside as
  `zdbf.corrupt-<time>.db` and the newest healthy backup from `data/db_backups/` is restored
  automatically. A critical alert is sent through `/fw alerts` routing.
* A backup is taken before any framework or user migration runs.
* `/fw db` can schedule a restore from any backup. It is applied on the **next start**, never
  while the bot is running; the replaced file is kept as `zdbf.replaced-<time>.db`.

