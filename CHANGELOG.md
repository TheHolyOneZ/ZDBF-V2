# Changelog

## 2.0.0 - 2026-11-10

A complete rewrite. See [docs/MIGRATING.md](docs/MIGRATING.md) for upgrading from V1.

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
