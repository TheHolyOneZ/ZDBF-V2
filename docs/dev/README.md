# Developer guide

How ZDBF V2 is put together, and how to work on it or build on it. If you only want to add a
feature to your own bot, start with [extensions.md](extensions.md). If you want to change the
framework itself, read this page first.

| Page | Covers |
|---|---|
| [extensions.md](extensions.md) | Writing an extension: commands, metadata, hot reload, config, permissions, scheduler, alerts, V1 compatibility, publishing |
| [dashboard-panels.md](dashboard-panels.md) | Giving an extension its own page in the web dashboard |
| [database.md](database.md) | The database API, key/value storage, migrations, atomic files |
| [ui-kit.md](ui-kit.md) | Components V2 cards, views, pagination, confirmations and modals |
| [hooks-and-events.md](hooks-and-events.md) | The event hook bus, built-in events, circuit breakers |
| [dashboard-internals.md](dashboard-internals.md) | How the web dashboard is built, adding bot actions and pages, running it locally |
| [dashboard-protocol.md](dashboard-protocol.md) | Pairing, signed requests, channels and the security model |

- [Project layout](#project-layout)
- [How the bot starts](#how-the-bot-starts)
- [What happens when a command runs](#what-happens-when-a-command-runs)
- [Services on the bot object](#services-on-the-bot-object)
- [Built-in modules](#built-in-modules)
- [Development setup](#development-setup)
- [Tests](#tests)
- [Conventions](#conventions)
- [Tools](#tools)

## Project layout

```
zdbf/
  __main__.py        command line: python -m zdbf [--check] [--config] [--env]
  core/
    bot.py           ZDBFBot: startup, prefixes, checks, slash sync, status, maintenance
    config.py        config.toml + .env + runtime overrides, validated with pydantic
    default_config.toml
    database.py      SQLite (aiosqlite): one writer, one reader, transactions, backups, recovery
    migrations/      the framework's own schema migrations
    storage.py       atomic file writes with locks and a cache (also importable as atomic_file_system)
    extensions.py    loading, unloading, reloading, hot reload watcher, V1 setup shim
    plugins.py       extension metadata, dependency and conflict checks
    hooks.py         the event hook bus and circuit breaker
    permissions.py   owner_only, admin_or_owner, guild_owner_or_owner, role restrictions
    alerts.py        alert routing per system
    slash_guard.py   keeps the slash command tree under Discord's limits
    cron.py          cron parser
    ipc.py           signed cluster IPC
    errors.py        error cards and reference codes
    metrics.py, cache.py, logging.py, schema.py
  ui/                Components V2 kit: cards, BaseView, Paginator, confirm, FormModal, lists
  cogs/              the built-in modules (automations/, backup/ and dashboard/ are packages)
  marketplace/       ZSync Marketplace client (separate license)
dashboard/           the web dashboard: PHP, JavaScript and CSS, uploaded to a web host
extensions/          user extensions, loaded and hot-reloaded at runtime
migrations/          user and extension migrations (NNN_name.py)
tools/               migrate_v1, selftest, gen_commands, strip_comments, dashboard_dev_router
tests/               pytest suite, plus tests/dashboard/php for the PHP side
```

## How the bot starts

1. `zdbf/__main__.py` loads `.env`, writes a default `config.toml` if there is none, validates the
   configuration and starts `ZDBFBot`.
2. `ZDBFBot.__init__` sets the intents from `[bot] privileged_intents`, creates the services
   (database, hook bus, plugin registry, alerts, slash guard, extension manager) and adds the
   global checks: parent group checks, per-server role restrictions and the default cooldown.
3. `setup_hook`:
   1. connects the database. A pending restore is applied, the file is checked, and a damaged
      file is replaced by the newest backup. Core migrations run.
   2. loads alert routing, plugin settings and disabled hooks, and starts the hook worker.
   3. reads the application owners from Discord.
   4. loads the always-on compatibility module, then every built-in module that `[modules]`
      enables.
   5. loads the user extensions in `extensions/`. An extension waiting for a dependency is retried
      after the others, so load order between extensions does not matter.
   6. starts the hot reload watcher, the status rotation and the maintenance loop.
   7. syncs slash commands if they changed.
4. On `on_ready` the `bot_ready` event is emitted.

## What happens when a command runs

```
message or interaction
  └─ prefix resolution (per-server prefix, @mention)       bot._resolve_prefix
  └─ V1 alias rewrite (!backupcreate → backup create)      bot.get_context
  └─ global checks                                          parent_checks, role_permission_check, _default_cooldown
  └─ command checks                                         @owner_only(), @admin_or_owner(), Discord permissions
  └─ on_command: metrics, usage stats, "command_executed" event
  └─ the command
  └─ errors → errors.py: an explained card, or a reference code plus a traceback to the log and alerts
```

Every command is a hybrid command, so the same code serves `/slash` and `!prefix`. `ctx.send()`
works for both.

## Services on the bot object

Extensions and modules reach everything through `bot`:

| Attribute | Type | Use |
|---|---|---|
| `bot.config` | `Config` | `get("section.key")`, `await set(...)`, `settings` (typed), `secrets` |
| `bot.db` | `Database` | Queries, transactions, per-server settings, key/value. See [database.md](database.md). |
| `bot.hooks` | `HookBus` | Events. `bot.register_hook` and `bot.emit_hook` are shortcuts. See [hooks-and-events.md](hooks-and-events.md). |
| `bot.alerts` | `AlertManager` | `await bot.alerts.send(system, message, level)` |
| `bot.ext` | `ExtensionManager` | `load`, `unload`, `reload`, `discover`, failed extensions and tracebacks |
| `bot.plugins` | `PluginRegistry` | Extension metadata and validation |
| `bot.metrics` | `MetricsCollector` | Command counts, errors, rates |
| `bot.slash_guard` | `SlashGuard` | The slash command budget |
| `bot.owner_id_set` | `set[int]` | Every owner. Use `await bot.is_owner(user)` for checks. |
| `bot.version`, `bot.started_at` | | Framework version, start time |

## Built-in modules

Each module is a discord.py extension under `zdbf/cogs/` (the marketplace under
`zdbf/marketplace/`), listed in `BUILTIN_MODULES` in `zdbf/core/extensions.py` and switched by
`[modules]`.

| Module | Package | Cog names |
|---|---|---|
| `core` | `zdbf.cogs.core` (+ `help.py`) | General |
| `admin` | `zdbf.cogs.admin` | Framework, Config Validator |
| `settings` | `zdbf.cogs.settings` | Server Settings |
| `diagnostics` | `zdbf.cogs.diagnostics` | Diagnostics, Database Migrations |
| `eventhooks` | `zdbf.cogs.eventhooks` | Event Hooks |
| `plugins` | `zdbf.cogs.plugins` | Plugins |
| `scheduler` | `zdbf.cogs.scheduler` | Task Scheduler |
| `automations` | `zdbf.cogs.automations` | Automations |
| `backup` | `zdbf.cogs.backup` | Backup |
| `shards` | `zdbf.cogs.shards` | Shard Monitor |
| `cluster` | `zdbf.cogs.cluster` | Cluster |
| `marketplace` | `zdbf.marketplace.cog` | Marketplace |
| `dashboard` | `zdbf.cogs.dashboard` | Dashboard |

`zdbf.cogs.compat` is always loaded. It provides the V1 command names as prefix aliases.

## Development setup

```bash
git clone https://github.com/TheHolyOneZ/ZDBF-V2
cd ZDBF-V2
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env              # a token of a test bot
python -m zdbf
```

Use a separate test bot and a test server. Edit files in `extensions/` while the bot runs: they
reload within seconds. Changes to `zdbf/` need a restart, or `/ext reload <module>` for a cog such
as `/ext reload backup`.

Do not sync throwaway slash commands to Discord over and over: Discord allows 200 command
creations per day per scope. Use prefix commands while iterating, or keep `sync_on_start = false`
and sync once with `/fw sync`.

## Tests

```bash
ruff check .                         # lint, as CI does
pytest -q                            # offline tests, no Discord needed
php tests/dashboard/php/run.php      # PHP side of the dashboard
python tools/selftest.py             # live: runs commands on a real server with the token from .env
python tools/selftest.py --deep      # also creates and deletes channels, roles, backups and panels
```

`selftest.py` takes `--guild` and `--channel` to choose where it runs, `--keep` to keep its
messages, and command names to run only those. Use a dedicated test server for `--deep`.

The dashboard end-to-end test starts PHP's built-in server, runs setup, pairs, runs commands and
tries the attacks. It needs PHP with the SQLite PDO driver, or a MySQL database given as
`ZDBF_TEST_MYSQL=host:port:database:user:password`. See [dashboard-internals.md](dashboard-internals.md#tests).

CI runs `ruff` and `pytest` on Python 3.12, 3.13 and 3.14, and checks the PHP side on 8.1 and 8.4.

## Conventions

- **Components V2 everywhere.** Replies are `LayoutView`s built with `zdbf.ui`. No embeds in new code.
- **Restrained look.** Only status dots (🟢🟡🔴⚪) as emoji in framework output. Decorative emoji
  are opt-in through `[ui] decorative_emoji`. `tests/test_ui_limits.py` enforces this.
- **Paginate** anything that can grow: lists, logs, search results. Discord's limits are hard errors.
- **Group commands.** New commands go into a group of their module. Owner-only groups use `@owner_only()`.
- **Schema changes are migrations.** Add an entry to `zdbf/core/migrations/__init__.py`; never
  edit one that has shipped.
- **Keep V1 extensions working.** The V1 APIs listed in [extensions.md](extensions.md#v1-compatibility)
  are part of the public surface.
- **No comments in the source.** The code is kept comment-free on purpose; names and small
  functions carry the meaning. Run `python tools/strip_comments.py --write` before committing.
  Every file starts with an SPDX header, which is kept.
- **Licences.** Framework files use the Apache-2.0 header, `zdbf/marketplace/` the marketplace
  licence header.
- **Commands changed?** Run `python tools/gen_commands.py` to regenerate
  [docs/guide/commands.md](../guide/commands.md).

## Tools

| Tool | Does |
|---|---|
| `tools/selftest.py` | Live test run on a Discord server |
| `tools/gen_commands.py` | Regenerates `docs/guide/commands.md` from the loaded commands |
| `tools/strip_comments.py [paths] [--write] [--keep-docstrings]` | Removes comments (dry run without `--write`) |
| `tools/migrate_v1.py <v1-folder> [--dest] [--dry-run] [--force]` | Imports a V1 installation |
| `tools/dashboard_dev_router.php` | Router for running the dashboard with PHP's built-in server |

Contributing rules and the pull request checklist: [CONTRIBUTING](../../.github/CONTRIBUTING.md).
