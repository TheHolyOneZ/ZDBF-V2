# Migrating from V1

```bash
cd /path/to/zdbf-v2
python tools/migrate_v1.py /path/to/discord-bot-framework-main --dry-run   # preview
python tools/migrate_v1.py /path/to/discord-bot-framework-main             # migrate
python -m zdbf
```

The V1 folder is only read. Stop the V1 bot first so its databases are not in use.

## What moves over

| V1 | V2 |
|---|---|
| `config.json` + `.env` options | `config.toml` (validated) |
| `DISCORD_TOKEN`, `BOT_OWNER_ID`, shard & IPC values | `.env` |
| `data/<guild>/guild.db` prefixes, mention flags, usage stats | main database |
| Extension tables inside `guild.db` | kept as `data/<guild>/guild.db` (still reachable via `bot.db._get_guild_connection`) |
| `command_permissions` (global) | per-server role restrictions, assigned on first start |
| `data/main.db` scheduled tasks | scheduler (weekday numbers converted, see below) |
| `data/backups/` | backups (compressed, same IDs, pinned state and notes kept) |
| `data/event_hooks_creater.json` | automations (see below) |
| `data/marketplace/ZygnalID.txt` | ZSync ZDBF Key - **activation carries over** |
| Alert channels, plugin enforcement | alert routing, plugin settings |

## Things that changed

* **Commands are grouped.** `/backupcreate` is now `/backup create`, `/fw_diagnostics` is
  `/diag overview`, `/eh_list` is `/eventhooks list` and so on. The **old names still work as
  prefix commands** (`!backupcreate`). The [command reference](commands.md) lists every V1 name.
* **`!discordbotframework` / `!framework` / `!botinfo`** are aliases of `/about`.
* **Cron weekdays** follow standard cron now: `0` = Sunday (V1: `0` = Monday). Migrated tasks
  are converted automatically. Names (`mon-fri`) and macros (`@daily`) are supported.
* **Owner detection** is automatic (application owner / team). `BOT_OWNER_ID` is optional.
* **Database**: one `data/zdbf.db` instead of one file per server.
* **Automations**: V1 templates map to V2 templates (welcome, goodbye, reaction roles,
  word filter, levels, announcements, voice log, webhook bridge, join-to-create voice).
  * V1 **tickets** used reactions; V2 tickets use a button panel. Migrated ticket automations
    are imported **disabled** - open `/hooks info`, press **Edit**, choose a panel channel and save.
  * V1 kept XP only in memory, so there is no XP to import.
  * V1 hooks with an `actions` list become **Custom automations** with the same actions
    (`trigger_hook` becomes "Run another automation" and is pointed at the new IDs).
  * V1 conditions are converted: `role_hierarchy` becomes `has_role` / `role_above` /
    `role_below`, `user_age` becomes `account_age`, `custom_variable` becomes `variable`;
    `message_count`, `time_range` and `day_of_week` carry over.
* **Cluster IPC** is a new, authenticated protocol. All clusters must run V2, and
  `SHARD_IPC_SECRET` must be at least 16 characters (the V1 default `change_me_please` is refused).
* **Live Monitor** was rebuilt as the **ZDBF Dashboard** (`[modules] dashboard`, see
  [dashboard guide](dashboard.md)). It is a new website and a new protocol: upload the new files and
  pair again. V1 dashboard files, tokens and users are not imported.
* **Removed**: `GeminiService`, `GeminiServiceHelper` and `ZExtensionAI`. Heavy packages (torch, opencv, …) are no longer installed by default -
  `requirements-extensions.txt` lists common marketplace dependencies and `/marketplace fixdeps`
  installs what an extension is missing.
* **License**: Apache 2.0 for the framework; the marketplace client keeps its own license.

## After the migration

1. Start the bot and run `/fw integrity`.
2. Check `/hooks list` for automations that were imported disabled (tickets) and finish them.
3. Run `/schedule list` and `/schedule preview` on a task or two to confirm the times.
4. Check `/ext list` for V1 extensions that failed to load. `/marketplace fixdeps` installs missing
   packages; the full error of anything else is in `logs/errors.log` and on the dashboard's Extensions page.
5. Set alert channels again if you want them elsewhere: `/fw alerts`.

Every change between versions: [CHANGELOG.md](../../CHANGELOG.md).
