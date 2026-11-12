# Installation

This page takes you from nothing to a running bot, then shows how to keep it running on a server.

- [What you need](#what-you-need)
- [1. Create the Discord application](#1-create-the-discord-application)
- [2. Download and install](#2-download-and-install)
- [3. Add the token](#3-add-the-token)
- [4. Start the bot](#4-start-the-bot)
- [5. First steps in Discord](#5-first-steps-in-discord)
- [Keep it running](#keep-it-running)
- [Updating](#updating)
- [Folders the bot writes](#folders-the-bot-writes)

## What you need

- **Python 3.12, 3.13 or 3.14.** Check with `python --version` (on some systems `python3`).
- **Git**, or download the repository as a zip from GitHub.
- A machine that can stay online: your PC for testing, a VPS, a Raspberry Pi or a container for
  real use. The bot only makes outgoing connections, so no port has to be opened.

## 1. Create the Discord application

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and press
   **New Application**.
2. Open **Bot**. Press **Reset Token** and copy the token. Treat it like a password: anyone who has
   it controls your bot.
3. On the same page, under **Privileged Gateway Intents**, enable:
   - **Server Members Intent**: needed by backups, welcome messages, XP and most automations.
   - **Message Content Intent**: needed by prefix commands (`!help`) and message triggers.

   If you leave one off, remove it from `[bot] privileged_intents` in `config.toml`, otherwise
   Discord refuses the login.
4. Open **OAuth2 → URL Generator**, tick the scopes `bot` and `applications.commands`, choose the
   permissions (Administrator is simplest for a private bot), open the generated link and add the
   bot to your server.

You do not need the client ID or the client secret. The ID is read from Discord at login and the
secret is only used for the optional Discord login on the web dashboard.

## 2. Download and install

```bash
git clone https://github.com/TheHolyOneZ/ZDBF-V2
cd ZDBF-V2
python -m venv .venv
```

Activate the virtual environment:

| System | Command |
|---|---|
| Linux, macOS | `source .venv/bin/activate` |
| Windows (PowerShell) | `.venv\Scripts\Activate.ps1` |
| Windows (cmd) | `.venv\Scripts\activate.bat` |
| fish | `source .venv/bin/activate.fish` |

Then install:

```bash
pip install -e .
```

`pip install -r requirements.txt` works too. `requirements-extensions.txt` lists packages that
popular marketplace extensions use; you only need it if an extension asks for them, and the
marketplace can install missing packages for you.

## 3. Add the token

```bash
cp .env.example .env             # Windows: copy .env.example .env
```

Open `.env` and paste the token after `DISCORD_TOKEN=`. Nothing else in that file is required.
Every option in it is explained in [configuration.md](configuration.md#env).

## 4. Start the bot

```bash
python -m zdbf
```

With `pip install -e .` the shorter `zdbf` command works as well. On the first start the bot
writes a default `config.toml` next to `.env`, with every option commented. Stop the bot with
`Ctrl+C`.

Useful options:

```bash
python -m zdbf --check                      # validate config.toml and .env, then exit
python -m zdbf --config path/to/config.toml # use another config file
python -m zdbf --env path/to/.env           # use another .env file
python -m zdbf --version
```

The bot reads `config.toml`, `.env`, `data/` and `logs/` relative to the folder you start it from.
Always start it from the same folder.

## 5. First steps in Discord

1. Type `/help` in your server. If slash commands do not show yet, wait a minute or restart
   Discord; the first sync can take a moment. `!help` works immediately.
2. You are the bot owner automatically if you own the application, or if you are on the team that
   owns it. To add more owners, set `BOT_OWNER_ID` in `.env` or `owner_ids` in `config.toml`.
3. Run `/fw integrity` to check that intents, folders and the database are fine.
4. Set an alert channel with `/fw alerts` so errors and warnings reach you.
5. Try a feature: `/hooks create` for a welcome message, `/backup create` for a first backup.

## Keep it running

### Linux with systemd

Create `/etc/systemd/system/zdbf.service` and adjust the user and the path:

```ini
[Unit]
Description=ZDBF Discord bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=zdbf
WorkingDirectory=/home/zdbf/ZDBF-V2
ExecStart=/home/zdbf/ZDBF-V2/.venv/bin/python -m zdbf
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zdbf
journalctl -u zdbf -f            # follow the output
```

`/fw shutdown` stops the bot; with `Restart=on-failure` systemd leaves it stopped. Use
`sudo systemctl restart zdbf` to restart.

### Windows

Run the bot in a terminal you leave open, or create a task in Task Scheduler that starts
`C:\path\to\ZDBF-V2\.venv\Scripts\python.exe` with the argument `-m zdbf` and the bot folder as
"Start in".

### Hosting panels and containers

Any host that runs Python 3.12+ works. Set the start command to `python -m zdbf`, the working
directory to the bot folder, and keep `data/` on persistent storage: it holds the database,
backups and the dashboard link.

## Updating

```bash
git pull
pip install -e .
```

Then restart the bot. Database changes are applied automatically on start, and a backup is taken
first. Read the [CHANGELOG](../../CHANGELOG.md) before updating: new modules that are off by
default are not added to an existing `config.toml`, so add their switch yourself if you want them.

## Folders the bot writes

| Path | Contents | Back it up? |
|---|---|---|
| `config.toml` | Your settings | Yes |
| `.env` | Token and secrets | Yes, keep it private |
| `data/zdbf.db` | The database: settings, automations, schedules, stats | Yes |
| `data/db_backups/` | Rolling database backups | Optional |
| `data/config_overrides.json` | Settings changed from Discord | Yes |
| `data/` (other) | Server backups, ticket transcripts, dashboard link, marketplace key | Yes |
| `logs/` | Rotating log files | No |
| `extensions/` | Your extensions and installed marketplace extensions | Yes |

Next: [configuration](configuration.md) · [commands](commands.md) · [troubleshooting](troubleshooting.md)
