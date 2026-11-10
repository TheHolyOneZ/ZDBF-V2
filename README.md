<div align="center">

<img src="assets/banner.png" alt="Zoryx Discord Bot Framework" width="720">

# Zoryx Discord Bot Framework V2

A modular Discord bot you can run as it is or build on. Every message is a Components V2 layout.

[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-3776AB)](https://www.python.org/downloads/)
[![discord.py](https://img.shields.io/badge/discord.py-2.7-5865F2)](https://github.com/Rapptz/discord.py)
[![License](https://img.shields.io/badge/license-Apache--2.0-2F855A)](LICENSE)

</div>

---

## What it is

ZDBF V2 is a complete rewrite of the Zoryx Discord Bot Framework. You get a ready bot with
server backups, no-code automations, a cron scheduler, diagnostics and an extension marketplace.
Every command works as a slash command and with a prefix. Developers can add their own
features as extensions, which reload when the file is saved.

| Area | In short |
|---|---|
| [Commands and help](#commands-and-help) | Hybrid `/slash` and `!prefix` commands in 15 groups, V1 names kept as aliases, help browser. |
| [Server settings](#server-settings) | Per-server prefix, @mention prefix, role requirements per command. |
| [Automations](#automations) | 11 templates and Custom automations with triggers, up to 15 actions, conditions and cooldowns. |
| [Backup and restore](#backup-and-restore) | Full server snapshots, diff, dry-run preview, selective restore, scheduled backups. |
| [Scheduler](#scheduler) | Cron tasks with time zones that post messages, emit events or write logs. |
| [Diagnostics and alerts](#diagnostics-and-alerts) | Health checks, loop lag, error tracking, integrity check, alerts routed per system. |
| [Extensions](#extensions-plugins-and-event-hooks) | Hot reload with rollback, dependency and conflict checks, event hooks with circuit breakers. |
| [ZSync Marketplace](#zsync-marketplace) | Browse, scan, install and update community extensions. |
| [Database](#database-and-storage) | One SQLite file, atomic writes, automatic recovery and rolling backups. |
| [Sharding and clusters](#sharding-and-clusters) | Shard monitor and multi-process clusters over authenticated IPC. |

## Quick start

You need Python 3.12, 3.13 or 3.14 and a bot application from the
[Discord Developer Portal](https://discord.com/developers/applications).

**1. Download and install**

```bash
git clone https://github.com/TheHolyOneZ/ZDBF-V2
cd ZDBF-V2
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .                 # or: pip install -r requirements.txt
```

**2. Add your token**

```bash
cp .env.example .env             # Windows: copy .env.example .env
```

Open `.env` and set `DISCORD_TOKEN`. It is the only required value.

**3. Enable the privileged intents**

In the Developer Portal, open your application, then **Bot**, and turn on **Server Members Intent**
and **Message Content Intent**. Backups and automations need the first, prefix commands need the
second. If you leave one off, remove it from `[bot] privileged_intents` in `config.toml`.

**4. Invite the bot**

Under **OAuth2**, generate an invite link with the `bot` and `applications.commands` scopes and add
the bot to your server.

**5. Start it**

```bash
python -m zdbf
```

On first start the bot writes a default `config.toml` next to `.env`. Type `/help` in your server,
or mention the bot to see its prefix. The application owner, or every member of the owning team,
is recognised as bot owner automatically.

You do not need the client ID or the client secret. The client ID is read from Discord at login,
and the secret is only used for website logins, which the bot does not do.

## Features

### Commands and help

- Every command is a hybrid command: it works as `/slash` and with the prefix (default `!`).
  Prefix commands are case-insensitive.
- Commands are grouped (`/backup create`), so the framework uses 15 of the 100 top-level slash
  commands Discord allows. V1 names such as `!backupcreate` still work with the prefix.
- If extensions push the total past 100, the extra commands stay available with the prefix instead
  of failing. `/diag commands` shows which ones were moved, and slots are refilled when an
  extension is unloaded.
- `/help` is an interactive guide: the bot's banner, avatar and description, then one card per
  category, each command with a **Details** page (slash and prefix usage, every option with its type,
  default and choices, who can use it, aliases, V1 names and cooldown) and a **Search** button that
  also finds old V1 names. It only lists commands the user can run. `/help <command>` opens a
  command directly, and an unknown name shows the closest matches.
- Commands without their own cooldown get a default one (`[cooldowns] default_rate` per
  `default_per` seconds, per user). Bot owners are exempt.
- Mentioning the bot shows a short card with the prefix and where to start.
- `/about` shows framework info and credits, `/ping` gateway, API and database latency, `/stats`
  uptime, members, command and error counts, memory and per-shard figures. `/stats commands` lists
  the most used commands per server or globally.
- Slash commands sync on start only when they changed, and again 10 seconds after an extension
  is loaded or unloaded. `/fw sync` syncs by hand: `changed` (default), `force`, `server` (an instant
  copy to the current server for testing) and `clear-server` (removes that copy again). Owner-only groups can be limited to development servers
  (`[bot] dev_guild_ids`) and are hidden from members without Administrator.
- Unexpected errors show the user a short reference code. The full traceback goes to the log and
  to the errors alert channel under the same code.
- Rotating bot status with placeholders (`{guilds}`, `{users}`, `{shards}`, `{commands}`,
  `{prefix}`, `{version}`), and an option to delete the invoking prefix message.

### Server settings

- `/settings prefix` sets a prefix per server, `/settings mentionprefix` allows or blocks
  `@Bot <command>`.
- `/settings permissions` requires roles for a command or a whole group. The server owner and
  administrators are never restricted.
- `/settings view` shows the current settings for the server.

### Automations

Created with a visual builder (`/hooks create`) and managed with `/hooks list`, `/hooks info`,
`/hooks toggle` and `/hooks history`.

| Template | What it does |
|---|---|
| Welcome | Greets new members with a card or text, gives an auto role, optional DM. |
| Goodbye | Posts a farewell when members leave. |
| Button roles | A panel with buttons that toggle roles, optionally one role at a time. Keeps working after restarts. |
| Reaction roles | Emoji-to-role mapping on an existing message, optional removal on un-react. |
| Word filter | Deletes, warns, times out or kicks on banned words. Whole-word and case options, ignored roles, log channel. |
| XP and levels | XP per message with a cooldown, level-up messages, reward roles, `/hooks rank` and `/hooks leaderboard`. |
| Recurring announcement | Posts a message every N hours. |
| Support tickets | A panel with an "Open ticket" button that creates private channels for the member and a support role. |
| Voice activity log | Logs voice joins, leaves, moves and mutes. |
| Join-to-create voice | Joining a hub channel creates a personal voice channel. |
| Webhook bridge | Forwards messages and joins to an external webhook (Discord, Zapier, Make). |

**Custom automations** combine one trigger with up to 15 actions:

- Triggers: a member joins or leaves, a message is sent (any, contains, exact, starts with or
  regex), a reaction is added, a member joins a voice channel, or a schedule.
- Actions: send a message or card, send a DM, add or remove a role, time out, call a webhook,
  create a role, wait, or run another custom automation (up to 5 levels deep).
- Conditions, combined with AND or OR: has or lacks a role, role above or below, in or not in
  channels, time range, day of week, account age, member age, chance, not a bot, message contains,
  message count and custom variables.
- Placeholders in text such as `{user}`, `{guild_name}`, `{member_count}`, `{date}`, plus
  `{random:1-10}` and `{math:...}`.
- Cooldowns per user or per server, and a run history for each automation.
- An automation that fails 10 times in a row is switched off and an alert is sent.
- Webhooks must use `https` and cannot point to local or private addresses.

### Backup and restore

Available to server administrators.

- `/backup create` captures roles, categories, channels (text, voice, forum with tags, permission
  overwrites, slowmode), emojis, stickers, server settings, icon and banner, member roles and the
  bot's settings for the server.
- Backups are compressed and carry a checksum. `/backup verify` checks it.
- `/backup restore` lets you pick components, choose whether existing items are updated and
  whether member roles are synced, then preview the result as a dry run before anything changes.
  Progress is shown live and a report follows.
- `/backup diff` compares a backup with another backup or with the current server.
- `/backup pin` protects a backup from rotation, `/backup note` attaches a note,
  `/backup schedule` creates backups every N hours.
- Limits per server, retention in days and a cooldown between manual backups are set in
  `[backup]`. `/backup audit` shows who created, restored or deleted backups.
- The bot owner can export any backup as JSON and see statistics across all servers.

### Scheduler

- `/schedule create` takes a standard 5-field cron expression (`0 9 * * mon-fri`), day and month
  names, or a macro such as `@daily`. `0` is Sunday, as in standard cron.
- Times use the time zone in `[scheduler] timezone` (any IANA name, for example `Europe/Berlin`).
- A task posts a message (text or card), emits an event hook, or writes a log entry. It can stop
  itself after a set number of runs.
- `/schedule preview` explains an expression and lists its next runs. `/schedule info` shows a
  task with buttons to enable, disable, run now or delete.
- Tasks persist across restarts. Failed runs can be reported to a channel (`/schedule alerts`).
- Extensions can create and remove tasks through the scheduler API.

### Diagnostics and alerts

Owner-only.

- `/diag overview` shows health status (healthy, degraded or critical), event-loop lag, error
  rate, latency and memory. A check runs every 5 minutes by default.
- `/diag history` shows past checks with trend lines, `/diag errors` recent command errors.
- `/diag migrations` and `/diag migrate` show and apply database migrations.
- `/fw integrity` checks configuration, database integrity, writable folders, atomic storage, the
  event hook worker, failed extensions, slash budget, intents, latency and disk space.
- Alerts are routed per system to a channel with `/fw alerts`: errors, diagnostics, event hooks,
  plugins, extensions, shards, cluster, backup, scheduler, automations, marketplace and database,
  with a default channel for the rest.

### Extensions, plugins and event hooks

- Python files in `extensions/` load on start and reload when saved. A broken edit is rolled back
  and the previous version keeps running. `[extensions] blacklist` skips files.
- `/ext list`, `load`, `unload`, `reload` and `info` manage them without a restart.
- Extensions can declare a version, dependencies with version ranges and conflicts. These are
  checked before loading, including dependency cycles. `/plugins` shows metadata, the dependency
  tree and validation results, and can switch enforcement off.
- The event hook bus lets extensions react to framework events with priorities and timeouts.
  Failing hooks trip a circuit breaker. `/eventhooks` lists hooks, shows history and enables,
  disables or resets them.
- Extensions get the Components V2 UI kit, per-server and global key/value storage, their own
  database tables through migrations, atomic JSON files, validated config sections and the
  scheduler.
- V1 extensions run unchanged, including `atomic_file_system` imports and the V1 hook and
  plugin calls.

Writing an extension: [docs/EXTENSIONS.md](docs/EXTENSIONS.md).

### ZSync Marketplace

- `/marketplace` browses extensions from the [ZSync Marketplace](https://zsync.eu/extension/).
  The marketplace license is accepted once per user.
- `/marketplace search` and `/marketplace info` find and describe extensions.
- `/marketplace install` downloads an extension and shows a safety scan first: imports, risky
  modules or calls (`subprocess`, `ctypes`, `socket`, ...) and whether it has a `setup` function.
  You confirm, then load it.
- `/marketplace updates` checks installed extensions for new versions, `/marketplace uninstall`
  unloads and deletes one, `/marketplace fixdeps` installs missing Python packages.
- `/marketplace key` shows this installation's ZSync ZDBF Key.

### Database and storage

- One SQLite file (`data/zdbf.db`) in WAL mode. Writes are committed atomically through one
  connection, reads use a second, read-only connection.
- The file is checked on every start. A damaged database is moved aside and the newest healthy
  backup is restored automatically, with a critical alert.
- Rolling database backups (7 kept, one every 24 hours by default), and one before every
  migration.
- `/fw db` shows statistics, takes a backup, runs a quick or full integrity check, and schedules a
  restore from any backup. The restore is applied on the next start, never while the bot runs.
- Hourly maintenance clears expired caches, old logs and `__pycache__` folders, checkpoints and
  optimises the database. Logs rotate by size and are kept 30 days by default.

Details: [docs/CONFIGURATION.md](docs/CONFIGURATION.md#database-safety).

### Sharding and clusters

- Automatic sharding, or manual with `SHARD_COUNT` and `SHARD_IDS`.
- `/shard monitor`, `health` and `details` show per-shard latency, uptime, reconnects and event
  throughput. Alerts fire after a set number of failures and again on recovery.
- With `[modules] cluster = true`, several processes or machines connect over IPC. Every frame is
  signed with HMAC-SHA256 and checked for age and replays. `/cluster` lists clusters, runs
  connection diagnostics and broadcasts messages.

### Interface

- Every reply is a Components V2 layout: containers, sections, selects and modals, no embeds.
- Menus belong to the person who opened them, disable themselves on timeout, and paginate
  anything that could exceed Discord's limits.
- The visual style is restrained: status dots only. Decorative emoji can be turned on with
  `[ui] decorative_emoji`.
- `[ui] help_banner` sets the image on top of `/help` (otherwise the bot's profile banner is used),
  `[ui] support_url` adds a "Support server" button, and public bots get an "Invite" button
  (`invite_button`, `invite_permissions`).

## Configuration

Settings live in `config.toml`, secrets in `.env`. Changes made from Discord (`/fw config set`,
`/fw modules`) are stored as overrides, so your file and its comments are never rewritten.
`/fw config reload` re-reads both files without a restart.

```bash
python -m zdbf --check                    # validate config.toml and .env, then exit
python -m zdbf --config path/to/config.toml
```

| `.env` key | Purpose |
|---|---|
| `DISCORD_TOKEN` | Required. The bot token. |
| `BOT_OWNER_ID` | Extra owner IDs, comma separated. |
| `ZDBF_CONFIG` | Alternative path to `config.toml`. |
| `SHARD_COUNT`, `SHARD_IDS` | Manual sharding. Leave empty and Discord decides. |
| `SHARD_IPC_SECRET` | Cluster secret, at least 16 characters, identical on every process. |
| `SHARD_IPC_MODE`, `SHARD_CLUSTER_NAME`, `SHARD_IPC_HOST`, `SHARD_IPC_PORT` | Per-process cluster settings. |

Every built-in module (core, admin, settings, diagnostics, eventhooks, automations, plugins,
scheduler, backup, shards, cluster, marketplace) can be switched off in `[modules]` or live with
`/fw modules`. The full `config.toml` reference is in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Commands

| Group | Purpose | Who can use it |
|---|---|---|
| `/help` `/about` `/ping` `/stats` | Help browser, framework info, latency, statistics | Everyone |
| `/settings` | Server prefix, mention prefix, role requirements per command | Manage Server; role requirements: server owner |
| `/hooks` | Automations, visual builder, XP rank and leaderboard | Manage Server; rank and leaderboard: everyone |
| `/schedule` | Cron tasks | Manage Server |
| `/backup` | Create, diff, verify, restore with preview, scheduled backups | Administrator |
| `/marketplace` | Browse, install, update and remove ZSync extensions | Browsing: everyone; installing: bot owner |
| `/plugins` | Plugin metadata, dependency tree, validation | Viewing: everyone; changes: bot owner |
| `/fw` | Sync, caches, database, integrity, cleanup, config, alerts, modules, shutdown | Bot owner |
| `/ext` | Load, unload and reload extensions | Bot owner |
| `/diag` | Health dashboard, history, errors, migrations, slash budget | Bot owner |
| `/eventhooks` | Framework event hooks and circuit breakers | Bot owner |
| `/shard` | Per-shard health and metrics | Bot owner |
| `/cluster` | Multi-process cluster status (when `[modules] cluster` is on) | Bot owner |

Every command with its arguments and V1 name: [docs/COMMANDS.md](docs/COMMANDS.md).

## Upgrading from V1

Stop the V1 bot, then run the migration from the V2 folder. The V1 folder is only read.

```bash
python tools/migrate_v1.py /path/to/v1 --dry-run     # preview
python tools/migrate_v1.py /path/to/v1               # migrate
python -m zdbf
```

Config, prefixes, permissions, scheduled tasks, backups, automations and your marketplace key
carry over. V1 command names still work with the prefix (`!backupcreate`). The live web dashboard,
`GeminiService`, `GeminiServiceHelper` and `ZExtensionAI` were removed in V2.
Details: [docs/MIGRATING.md](docs/MIGRATING.md). All changes: [CHANGELOG.md](CHANGELOG.md).

## For developers

```
zdbf/
  core/          bot, config, database and migrations, storage, hooks, plugins,
                 permissions, alerts, cron, IPC, slash guard
  ui/            Components V2 kit: cards, views, paginator, confirm
  cogs/          built-in modules (automations/ and backup/ are packages)
  marketplace/   ZSync Marketplace client, separate license
extensions/      your extensions
tools/           migrate_v1.py, selftest.py, gen_commands.py, strip_comments.py
tests/           pytest suite
```

```bash
pip install -e ".[dev]"
ruff check .
pytest
python tools/selftest.py --deep           # live run, see below
python tools/gen_commands.py              # regenerate docs/COMMANDS.md
```

CI runs `ruff` and `pytest` on Python 3.12, 3.13 and 3.14. `selftest.py` logs in with the token
from `.env` and runs a set of commands in a real server (`--guild` and `--channel` pick where).
With `--deep` it also creates and deletes channels, roles, backups and panels, so use a dedicated
test server only.

The source is kept free of comments on purpose. Read [CONTRIBUTING](.github/CONTRIBUTING.md)
before opening a pull request, and report vulnerabilities as described in
[SECURITY](.github/SECURITY.md).

## License

ZDBF V2 is licensed under the [Apache License 2.0](LICENSE). Redistributions must keep the
[NOTICE](NOTICE) file. The ZSync Marketplace client (`zdbf/marketplace/`) is covered by the
[ZSync Marketplace License](LICENSE-MARKETPLACE), and extensions downloaded through it may carry
their own licenses. The names Zoryx, ZDBF, ZSync, TheHolyOneZ and TheZ are not licensed as
trademarks.

Created by **TheHolyOneZ**.
