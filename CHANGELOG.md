# Changelog

## Unreleased

### Dashboard
- New **ZDBF Dashboard**, the successor of V1's Live Monitor: a web control panel made of real
  PHP, JavaScript and CSS files that you upload to ordinary web hosting (PHP 8.1+, SQLite or
  MySQL/MariaDB). Opt-in with `[modules] dashboard = true`. Guide: `docs/guide/dashboard.md`.
- The bot and the website can run on different machines. The bot only makes outgoing HTTPS
  requests, so the bot host needs no open port.
- `/dashboard export` builds the folder with a setup key, `setup.php` installs it and locks itself,
  `/dashboard pair` connects the bot. The shared secret is derived on both sides and never sent.
- Every request and response is signed (HMAC-SHA256 over method, path, time, nonce and body),
  with replay and clock-skew protection. Nothing secret travels in a URL.
- The bot enforces its own rules: a capability list that only the bot owner can change
  (`/dashboard capabilities`, `[dashboard]`), approval in a Discord DM for dangerous actions,
  a file sandbox, one run per command, a bot-side audit log (`/dashboard audit`) and
  `/dashboard lock` for view-only.
- Website: live overview with charts and a table view, bot link page, users and roles, audit
  logs, sessions, two-factor login with recovery codes, optional Discord login, command palette,
  light and dark theme, phone layout. Updates arrive within about a second through held requests,
  with polling as the fallback.
- **Chat as the bot**: channel tree with threads and direct messages, live history (new messages,
  edits, deletions and reactions appear as they happen), send, reply, edit, delete, react, pin and
  attachments. Cards, embeds, mentions and Discord formatting are rendered like in Discord.
- **Run commands from the browser**: every command with a form for its options, run in a channel
  you choose, with the answer shown on the page. Commands run with the rights of an ordinary member
  (`commands.run`) or, when enabled and approved, of the bot owner (`commands.owner`). The bot
  posts each command in the channel with the name of the dashboard user.
- **Files**: a file manager for the allowed folders with a code editor, the changes shown before
  saving, reload of the extension after saving, chunked upload and download, rename, delete and a
  trash on the bot that keeps replaced and deleted files for 30 days.
- **Extensions**: load, unload and reload with the full error of a failed load, hot reload switch,
  and the ZSync Marketplace with a file check and install including missing Python packages.
- **Logs**: live log tail with level filter, text filter and a search of the log file. Tokens and
  secrets are hidden before a line leaves the bot.
- **Configuration**: every setting as a form (runtime overrides) or `config.toml` in the editor,
  checked by the bot before use, with the last 10 versions kept. The website cannot change
  `[dashboard]`, the dashboard module switch or `bot.owner_ids`.
- **Servers**: server details, prefix and command restrictions, backups with compare, restore
  preview and restore, and leaving a server.
- **Automations**: automations edited with forms built from their templates, conditions and run
  history; scheduled tasks with a cron explanation, run now and pause.
- **System**: health trends, shards and cluster, event hooks, plugins, alerts, the status rotation
  and shutdown. **Database**: a read-only browser that hides secret-looking columns.
- **Panels for extensions**: extensions can add dashboard pages as plain data (stats, tables, forms,
  buttons) with Python handlers and their own capabilities.
- **Tickets**: open tickets with Close, and the transcripts of closed tickets.
- `/dashboard recover` resets a lost owner password on the website with a code sent by the bot.
  Website settings for held requests and the visitor address header.
- Command palette with sub-pages, servers and extension panels; keyboard shortcuts (`?` lists them).
- `/fw alerts` has a `dashboard` system. Recent alerts are kept in memory for the overview.
- **Design**: glass panels over a moving background that reacts to commands, chat messages and
  errors, a 3D mark on the login pages, motion for page changes, lists and numbers, and the
  dashboard's own dropdowns, switches and check boxes. Reduced motion, data saver and browsers
  without WebGL get a calm version. See "Look and motion" in `docs/guide/dashboard.md`.
- Updates show up at once, also behind a CDN: every style and script link carries the time its
  file last changed.
- Restores started from the dashboard show their current step.

### Backups
- A restore with "update existing" only edits channels and categories that differ from the backup.
  Before, it edited every channel, which ran into Discord's limit of two changes per channel in ten
  minutes and made a second restore wait for many minutes.
- A change that Discord holds back for more than 25 seconds is skipped and listed in the report;
  the rest of the restore continues.

### Extensions
- Extensions written for older discord.py (a plain `def setup(bot)` that does not await
  `add_cog`) load in a compatibility mode instead of failing with "object can't be awaited".

### Automations
- Closing a support ticket now saves a transcript (messages, authors, times, attachment links) under
  `data/tickets/`, and can post it as a text file to a channel you choose. On by default, switch it
  off in the ticket automation's settings. The dashboard lists open tickets and transcripts.

### Marketplace
- Installing an extension now finds the Python packages it needs that are missing and offers
  **Install and load**: the bot installs them with pip (uv as a fallback) and loads the extension
  right away. Only the bot owner can do this, the exact command is shown first, optional imports
  (inside `try/except ImportError` or `if TYPE_CHECKING`) are skipped, and unusual package names
  are refused. `[marketplace] auto_install_packages = false` switches it off.
- `/marketplace fixdeps` uses the same installer, so it also works in uv environments without pip.

### Security
- **Owner-only command groups did not protect their subcommands.** discord.py does not run a
  group's checks when one of its subcommands is invoked, so the bot-owner check on `/fw`, `/ext`,
  `/diag`, `/shard`, `/cluster` and `/eventhooks` only guarded the bare group. With the prefix any
  member could run commands such as `!fw shutdown`, `!fw config set` or `!ext load`; by slash any
  server administrator could. A check on a group now applies to everything below it, for prefix and
  slash commands, and for groups in extensions too. Update as soon as you can.

### Documentation
- New documentation layout: `docs/README.md` is the index, `docs/guide/` holds the user guide
  (installation, configuration, commands, automations, backups, scheduler, marketplace, dashboard,
  operations, migrating, troubleshooting) and `docs/dev/` the developer guide (architecture,
  extensions, dashboard panels, database, UI kit, event hooks, dashboard internals and protocol).
- The old `docs/COMMANDS.md`, `CONFIGURATION.md`, `DASHBOARD.md`, `EXTENSIONS.md` and `MIGRATING.md`
  moved into those folders. `tools/gen_commands.py` now writes `docs/guide/commands.md`.
- The README is rewritten for people who want to run the bot, with every feature and a short FAQ.

## 2.0.0 - 2026-11-10

A complete rewrite. See [docs/guide/migrating-from-v1.md](docs/guide/migrating-from-v1.md) for upgrading from V1.

### Architecture
- Installable `zdbf` package (`python -m zdbf`) replacing the monolithic `main.py`.
- Python 3.12 - 3.14, discord.py 2.7; CI on all three versions.
- `config.toml` validated with pydantic, secrets in `.env`, runtime overrides that never rewrite your file.
- One SQLite database (WAL) with versioned migrations instead of a file per server.
- Atomic storage now fsyncs and uses `os.replace` (atomic on Windows too).
- Built-in modules can be toggled in `[modules]` or live with `/fw modules`.
- Single error handler for prefix, hybrid and slash commands with reference IDs for unexpected errors.
- Central alert routing (`/fw alerts`) shared by all systems.
- Database hardening: committed-only reader connection, retries on lock contention, automatic
  recovery from a corrupt file, backups before migrations, scheduled restores, WAL checkpoints,
  multi-step writes in single transactions and fsynced files and directories.
- Hourly maintenance: cache expiry, old logs, `__pycache__` in `extensions/`, legacy V1
  connections of servers the bot left, WAL checkpoint, `PRAGMA optimize`, interval backups.

### Interface
- Every message is a Components V2 layout; shared UI kit (`zdbf.ui`) with cards, paginators,
  confirmations, forms and owner-locked self-disabling views.
- Commands grouped into 15 top-level slash commands (V1 used ~60 and needed the slash limiter).
  V1 command names keep working as prefix aliases.
- Interactive help guide: category cards, per-command pages with usage, option types, defaults and
  choices, access level and cooldown, search (including V1 names), Support and Invite buttons.
- `/fw sync` modes: `changed`, `force`, `server` (instant test copy) and `clear-server`.
- A configurable default cooldown for every command without its own (`[cooldowns]`).
- Owner command groups are hidden from regular members and can be limited to `dev_guild_ids`.
- Slash commands only re-sync when they actually changed (hash comparison), automatically after reloads.
- Restrained visual language: no decorative emoji (only status dots), consistent headers and footers,
  sentence-case copy. `[ui] decorative_emoji` brings title emoji back.
- Everything that can grow is paged: lists, selects (any number of options), detail pages,
  reports and diffs. Oversized static messages become paginators automatically.

### Systems
- **Extensions**: dependency / conflict / cycle checks before import (static metadata), dependency-ordered
  loading, hot reload of packages, failed-extension tracking.
- **Automations** (was EventHooksCreater): visual no-code builder with channel/role pickers, JSON conditions,
  new button-role panels and button-based ticket panels (persistent across restarts), persistent XP with
  `/hooks rank` and `/hooks leaderboard`, auto-disable after repeated errors.
  **Custom automations**: one trigger and up to 15 chained actions (message, DM, roles, timeout,
  webhook, create role, wait, run another automation) with a visual action editor, loop and depth
  guards. Variables `{date}`, `{time}`, `{timestamp}`, `{random:a-b}`, `{math:...}` and more;
  conditions `role_above`, `role_below`, `message_count`, `variable`; per-automation cooldowns;
  run history with `/hooks history` and success rates.
- **Scheduler**: standard cron (names, macros, ranges with steps, DOM/DOW semantics), time zones,
  no double-firing, run-now, previews of upcoming runs.
- **Backup & restore**: compressed snapshots, dry-run preview, "update existing" mode, forum tags, role icons,
  role order, server images, bot settings incl. command permissions, diffs against the live server, audit log,
  rotation of unpinned backups.
- **Diagnostics**: 1-second loop-lag sampling, health history with sparklines, integrity check, slash budget.
- **Cluster IPC**: HMAC challenge-response auth (the secret is never sent), signed frames, replay and
  staleness protection, request/response API for extensions.
- **Marketplace**: rebranded to **ZSync**; the ZygnalID is now the **ZSync ZDBF Key** (migrated automatically);
  redesigned browser with filters, search and sorting; update checks; uninstall; static safety scan before
  install; `fixdeps` installs into the bot's own environment with a confirmation.

### Tools
- `tools/migrate_v1.py` - import a V1 installation.
- `tools/selftest.py` - live end-to-end test on a test server (`--deep` covers backup/restore, panels,
  custom automations, the slash budget guard, backup paging and the scheduler).
- `tools/gen_commands.py` - generates `docs/COMMANDS.md`.

### Removed
- Live Monitor web dashboard, GeminiService, GeminiServiceHelper, ZExtensionAI.
- Heavy default dependencies (torch, torchvision, opencv, sentence-transformers, google-generativeai).
- V1's slash command limiter, replaced by the slash budget guard: commands over Discord's 100 limit
  fall back to prefix-only instead of breaking extension loading.

### License
- The framework is now **Apache 2.0** with a NOTICE file. The ZSync Marketplace client and downloaded
  extensions are covered by the ZSync Marketplace License.

## 1.x

See the V1 repository history.
