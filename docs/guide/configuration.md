# Configuration

ZDBF reads its settings from three places:

| Source | For | Who edits it |
|---|---|---|
| `config.toml` | Every setting an operator chooses | You. Written with defaults and comments on the first start. |
| `.env` | The token and other secrets, plus values that differ per process | You |
| `data/config_overrides.json` | Changes made from Discord or the dashboard (`/fw config set`, `/fw modules`, `/dashboard capabilities`, `/shard alerts`) | The bot |

Overrides are layered on top of `config.toml`, so your file and its comments are never rewritten.
`/fw config unset <key>` removes an override and the value from the file applies again.

- [Checking and reloading](#checking-and-reloading)
- [`.env`](#env)
- [Sections at a glance](#sections-at-a-glance)
- [Turning modules on and off](#turning-modules-on-and-off)
- [Owners](#owners)
- [Status rotation](#status-rotation)
- [The full default file](#the-full-default-file)
- [Settings for extensions](#settings-for-extensions)

## Checking and reloading

```bash
python -m zdbf --check          # validate config.toml and .env, then exit
```

In Discord (bot owner):

| Command | Does |
|---|---|
| `/fw config validate` | Check the file and the config sections of extensions |
| `/fw config show [section]` | The effective values, secrets hidden |
| `/fw config schema` | Every key with its type |
| `/fw config set <key> <value>` | Set a runtime override, for example `/fw config set backup.max_per_guild 50` |
| `/fw config unset <key>` | Remove an override |
| `/fw config reload` | Re-read `config.toml` and `.env` without a restart |

A reload covers almost everything. Intents, sharding, the database path and logging need a restart.

## `.env`

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN` | **Required.** The bot token. |
| `BOT_OWNER_ID` | Extra owner IDs, comma separated. The application owner or team is detected automatically. |
| `ZDBF_CONFIG` | Another path for `config.toml` (same as `--config`). |
| `SHARD_COUNT`, `SHARD_IDS` | Manual sharding for this process. Leave both empty and Discord decides. |
| `SHARD_IPC_SECRET` | Cluster secret, at least 16 random characters, identical on every process. |
| `SHARD_IPC_MODE` | `server` on exactly one process, `client` on all others. |
| `SHARD_CLUSTER_NAME` | Name of this process in `/cluster status`, unique per process. |
| `SHARD_IPC_HOST`, `SHARD_IPC_PORT` | Where the cluster server listens and clients connect. |

Generate a cluster secret with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## Sections at a glance

| Section | Controls |
|---|---|
| `[bot]` | Prefix, mention prefix, extra owners, development servers, slash sync, intents |
| `[status]` | The rotating bot status |
| `[ui]` | Decorative emoji, the `/help` banner, support and invite buttons |
| `[maintenance]` | `__pycache__` cleanup and rolling database backups |
| `[database]` | Where the SQLite file lives |
| `[logging]` | Log level, folder, rotation and retention |
| `[extensions]` | Extension folder, auto load, hot reload, blacklist |
| `[cooldowns]` | The default cooldown for commands without their own |
| `[modules]` | Which built-in modules load |
| `[diagnostics]` | Lag and error thresholds, health check interval, how many commands before the error rate counts |
| `[backup]` | Backups per server, cooldown, automatic backups, retention |
| `[scheduler]` | Time zone and task limit per server |
| `[shards]` | Failures before a shard alert |
| `[cluster]` | Cluster mode, address and name |
| `[marketplace]` | Marketplace addresses, cache, automatic package install |
| `[dashboard]` | What the web dashboard may do, see [dashboard.md](dashboard.md#bot-side-settings) |

## Turning modules on and off

Every built-in module can be switched in `[modules]`, or live with `/fw modules <module> <enabled>`:

| Module | Default | What it adds |
|---|---|---|
| `core` | on | `/help`, `/about`, `/ping`, `/stats` |
| `admin` | on | `/fw`, `/ext`, config validation (cannot be unloaded) |
| `settings` | on | `/settings` |
| `diagnostics` | on | `/diag`, health checks, user migrations |
| `eventhooks` | on | `/eventhooks` |
| `automations` | on | `/hooks` and every automation |
| `plugins` | on | `/plugins`, dependency checks |
| `scheduler` | on | `/schedule` and the scheduler API for extensions |
| `backup` | on | `/backup` |
| `shards` | on | `/shard` |
| `cluster` | off | `/cluster` and IPC between processes |
| `marketplace` | on | `/marketplace` |
| `dashboard` | off | `/dashboard` and the web dashboard link |

A module that is new in an update is off in an existing `config.toml` until you add its line.

## Owners

Bot owners can run every owner-only command (🔒 in the [command reference](commands.md)). The bot
treats these accounts as owners:

1. The owner of the Discord application, or every member of the team that owns it.
2. IDs in `BOT_OWNER_ID` in `.env`.
3. IDs in `[bot] owner_ids`.

The web dashboard can never change `owner_ids`.

## Status rotation

`[[status.rotation]]` entries are shown one after the other, every `[status] interval` seconds.

```toml
[[status.rotation]]
presence = "online"     # online | idle | dnd | invisible
type = "watching"       # playing | watching | listening | competing | custom
text = "{guilds} servers"
```

Placeholders: `{guilds}`, `{users}`, `{shards}`, `{commands}`, `{prefix}`, `{version}`.

## The full default file

This is the `config.toml` the bot writes on its first start, with every option and its comment.

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
text = "Powered by ZDBF V2"

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
dashboard = false              # web control panel, see [dashboard] and docs/guide/dashboard.md

[diagnostics]
loop_lag_threshold_ms = 500
health_interval_minutes = 5
error_rate_warn_percent = 10.0 # share of commands that crashed (refused commands do not count)
error_rate_min_commands = 20   # judge the error rate only after this many commands in the last hour

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
auto_install_packages = true    # offer to pip-install an extension's missing packages and load it

# Web control panel. Enable the module above, run /dashboard export, upload the folder,
# then /dashboard pair. Everything in this section is enforced by the bot and can
# never be changed from the website.
[dashboard]
# What the website may do. Remove a line to switch that area off.
capabilities = [
    "view",              # status, statistics, lists
    "logs",              # live log tail
    "chat.read",         # read channels the bot can see
    "chat.send",         # send, edit and delete the bot's own messages, react
    "commands.run",      # run commands with the rights of an ordinary member
    "extensions",        # load, unload, reload
    "files.read",        # read files inside file_roots
    "automations",
    "scheduler",
    "settings",
    "backups",           # create, list, compare (restoring is "backups.restore")
    "presence",
    # Off unless you add them:
    # "chat.moderate",   # delete other members' messages, pin
    # "database",        # read-only database browser
    # "files.write",     # create, change, rename, delete files
    # "config",          # change config.toml and runtime overrides
    # "marketplace",     # install extensions and Python packages
    # "commands.owner",  # run commands with the rights of the bot owner
    # "backups.restore",
    # "guilds.leave",
    # "system",          # shut the bot down
]
# These wait for the bot owner to press Approve in a Discord DM.
approval = ["files.write", "config", "marketplace", "commands.owner", "backups.restore", "guilds.leave", "system"]
approval_timeout = 300         # seconds until an unanswered approval request is denied
file_roots = ["extensions"]    # folders the file manager may open, relative to the bot directory
max_file_kb = 1024             # largest file the dashboard may read or write
idle_interval = 45             # seconds between check-ins while nobody has the dashboard open
locked = false                 # true = view only (same as /dashboard lock)
```

## Settings for extensions

Extensions can read their own top-level table from `config.toml`, for example `[weather]`, and
register a schema so `/fw config validate` checks it. They cannot redefine a framework section.
How: [docs/dev/extensions.md](../dev/extensions.md#configuration).
