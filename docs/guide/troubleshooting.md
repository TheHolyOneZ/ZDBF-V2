# Troubleshooting

Start with `/fw integrity` (bot owner): it checks configuration, database, folders, extensions,
intents, the slash command budget, latency and disk space, and usually names the problem. If the
bot does not start at all, run `python -m zdbf --check` and read the last lines of `logs/zdbf.log`.

- [Starting](#starting)
- [Commands](#commands)
- [Features](#features)
- [Extensions](#extensions)
- [Web dashboard](#web-dashboard)
- [Asking for help](#asking-for-help)

## Starting

| Problem | What to do |
|---|---|
| `DISCORD_TOKEN is not set` | Copy `.env.example` to `.env` in the folder you start the bot from and add the token. |
| `Login failed - the DISCORD_TOKEN in .env is invalid` | Reset the token in the Developer Portal (**Bot → Reset Token**) and paste the new one. No quotes, no spaces. |
| `Discord rejected the privileged intents` | Enable **Server Members Intent** and **Message Content Intent** under **Bot** in the Developer Portal, or remove them from `[bot] privileged_intents`. |
| A config error on start | The message names the key. `python -m zdbf --check` validates without starting. |
| `ModuleNotFoundError` for `discord` or another core package | The virtual environment is not active, or the install step was skipped. Activate `.venv` and run `pip install -e .`. |
| Python version error | ZDBF needs Python 3.12, 3.13 or 3.14. |
| The bot starts with an empty config, or loses its data | It was started from another folder. Paths are relative to the folder you start it in. |
| An alert says the database was restored from a backup | The database file was damaged (often a power cut or a full disk) and was replaced by the newest healthy backup. The damaged file is kept as `data/zdbf.corrupt-<time>.db`. |

## Commands

| Problem | What to do |
|---|---|
| Slash commands do not show up | The first sync can take a minute; restart your Discord client. The invite needs the `applications.commands` scope. `/fw sync force` syncs now, `/fw sync server` makes them appear instantly in the current server. |
| Commands show up twice in one server | A server copy from `/fw sync server` is still there. Run `/fw sync clear-server`. |
| Prefix commands do nothing | Message Content Intent is off, or the server uses another prefix. Mention the bot to see the prefix. |
| Owner commands (`/fw`, `/ext`...) are missing | They are hidden from members without Administrator, and with `[bot] dev_guild_ids` set they only exist in those servers. |
| The bot refuses a command for a member | A role requirement is set with `/settings permissions`, or the command needs a Discord permission. `/help <command>` shows who can use it. |
| An extension's command only works with the prefix | More than 100 top-level slash commands are registered. `/diag commands` shows which were moved. Group commands to save slots. |
| A command answers with a reference code | It failed unexpectedly. The bot owner finds the traceback under that code in `/diag errors`, `logs/errors.log` and the `errors` alert channel. |

## Features

| Problem | What to do |
|---|---|
| Roles are not given (welcome, button roles, XP rewards, restore) | The bot needs **Manage Roles** and its own role must be above the roles it hands out. Drag it up in **Server Settings → Roles**. |
| An automation stopped working | It may have been switched off after 10 failures in a row. `/hooks history` shows the errors, `/hooks toggle` turns it back on. |
| Welcome or goodbye messages never fire | Server Members Intent is off. |
| A backup restore skipped some changes | Discord allows two name or topic changes per channel in ten minutes. Run the restore again later. Missing permissions are listed in the report. |
| A scheduled task runs at the wrong hour | Set `[scheduler] timezone` to your zone, for example `Europe/Berlin`. `/schedule preview` shows the next runs. |
| `/backup create` says to wait | A cooldown applies between manual backups (`[backup] cooldown_seconds`). |
| Marketplace downloads fail with a key error | The ZSync ZDBF Key is not activated yet. See [marketplace.md](marketplace.md#activate-your-key). |

## Extensions

| Problem | What to do |
|---|---|
| An extension does not load | `/ext list` shows it as failed with the reason. The full traceback is in `logs/errors.log` and on the dashboard's Extensions page. |
| "Missing dependencies" | It needs another extension (or a version of it) that is not loaded. `/plugins validate <name>` explains. |
| A Python package is missing | `/marketplace fixdeps`, or `pip install <package>` in the bot's virtual environment. |
| Saving a file changed nothing | The edit failed and the previous version kept running. The failure is in the log and the `extensions` alert channel. Hot reload checks every 5 seconds (`[extensions] hot_reload_interval`). |
| A file with spaces in its name | It is renamed to use underscores, since Python cannot import names with spaces. |

## Web dashboard

The dashboard has its own table of problems and fixes: [dashboard.md → Troubleshooting](dashboard.md#troubleshooting).

## Asking for help

Open an issue at [github.com/TheHolyOneZ/ZDBF-V2/issues](https://github.com/TheHolyOneZ/ZDBF-V2/issues/new/choose)
and include:

- the output of `python -m zdbf --version`,
- your operating system and how you run the bot,
- what you did and what happened,
- the relevant lines from `logs/zdbf.log` or `logs/errors.log`.

Remove your token and any secrets from what you paste. Report security problems privately, as
described in [SECURITY](../../.github/SECURITY.md).
