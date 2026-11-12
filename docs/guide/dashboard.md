# ZDBF Dashboard

A web control panel for a ZDBF V2 bot. You upload a folder of PHP, JavaScript and CSS files to
ordinary web hosting, pair it with your bot once, and manage the bot from the browser.

The bot and the website can run on different machines and networks. The bot connects out to the
website over HTTPS; the website never connects to the bot. The bot host needs no open port, no
public address and no firewall change.

- [Install](#install)
- [Pages](#pages)
- [Commands](#commands)
- [Bot-side settings](#bot-side-settings)
- [Capabilities](#capabilities)
- [Users, roles and logins](#users-roles-and-logins)
- [Hosting notes](#hosting-notes)
- [Troubleshooting](#troubleshooting)
- [Security in short](#security-in-short)

## Install

You need:

- a running ZDBF V2 bot, on any host
- web hosting with PHP 8.1 or newer, the PDO driver for SQLite or MySQL/MariaDB, OpenSSL, and HTTPS

The web host needs no Python, no Node, no shell access and no long-running process.

1. **Enable the module.** In `config.toml` set `dashboard = true` under `[modules]` and restart the
   bot (or run `/fw modules module:dashboard enabled:true`).
2. **Get the files.** Run `/dashboard export`. The bot builds `zdbf-dashboard.zip` and sends it to
   you privately together with a **setup key**. The key belongs to that archive: only someone who
   has it can finish the setup.
3. **Upload.** Unpack the archive and upload the contents of the `zdbf-dashboard` folder to your
   web host with FTP or the host's file manager, for example into `/dashboard`. Upload the hidden
   `.htaccess` files too.
4. **Run setup.** Open `https://your-site/dashboard/setup.php`. The page checks the host, then asks
   for the setup key, a database (SQLite needs nothing; for MySQL/MariaDB enter the database from
   your hosting panel) and the owner account. Setup locks itself when it is done.
5. **Pair.** The last setup page shows a command such as
   `/dashboard pair url:https://your-site/dashboard code:ABCD-EFGH-...`. Run it in Discord as the
   bot owner within 10 minutes. The shared secret is derived on both sides and is never sent.

The dashboard shows the bot as online a moment later. If the code expires, log in and create a new
one under **Bot link**.

**nginx.** nginx ignores `.htaccess`. Add the rules from `nginx.example.conf` to your server block
first. Setup tests from your browser whether the private folders can be opened and refuses to
continue while they can.

## Pages

| Page | What it does |
|---|---|
| **Chat** | Read and write as the bot. Pick a server channel, thread or direct message, read the history, and see new messages, edits, deletions and reactions as they happen. Send, reply, edit and delete the bot's messages, react, and attach up to three files (3 MB in total). The bot's own cards, embeds, mentions and Discord formatting are shown as in Discord. |
| **Commands** | Every command with its options as a form. Choose a channel and run it as the bot; the answer is shown on the page with a link to the message. |
| **Files** | The folders in `[dashboard] file_roots` as a tree. Open a file in the code editor (syntax colours, search, folding), see the changes before saving, and reload the extension the file belongs to right after. Create, upload, download, rename and delete files and folders, and download a whole folder as a zip (up to 64 MB, protected files left out). Replaced and deleted files go to a trash on the bot and can be restored for 30 days. |
| **Extensions** | Loaded, failed and available extensions with the full error of a failed load. Load, unload, reload, and hot reload on or off. The marketplace tab lists the ZSync Marketplace: check an extension's file (imports, entry point, missing packages, the code itself), then install it, install the Python packages it needs and load it in one step. |
| **Logs** | The bot log as it is written, filtered by level and text, with tracebacks folded. Pause, download, or search the last 16 MB of the log file. Tokens and secrets are hidden before a line leaves the bot. |
| **Configuration** | Every setting of `config.toml` as a form, saved as a runtime override that applies at once, or the file itself in the editor. The bot checks every change before using it, shows what changes and which settings need a restart, and keeps the last 10 versions of the file. |
| **Servers** | Every server the bot is in. Per server: details and the bot's permissions, prefix and command restrictions, backups (create, compare with the server, preview a restore, restore, pin, delete) and leaving the server. |
| **Automations** | The automations of a server with forms built from their templates, an action list editor for custom automations, conditions, run history, on/off and delete. The second tab lists scheduled tasks with a live explanation of the cron expression, run now, pause and delete. |
| **Tickets** | Open tickets of a server with a link into Chat and a Close button, and the transcripts of closed tickets to read, download as text or delete. |
| **System** | Health checks with trends, the caches (clear them with `settings`), shards and the cluster link, event hooks (turn a hook on or off), plugins and their problems, recent alerts and where they go, the bot's status rotation, and shutting the bot down. |
| **Database** | A read-only view of the bot's SQLite database: tables, rows, sorting and search. Columns named like tokens, secrets or passwords are hidden. |
| **Panels** | Pages that extensions add. See [Panels for extensions](#panels-for-extensions). |
| **Overview** | Live status: servers, members, commands, error rate, latency, uptime. Charts for CPU, memory, gateway latency, event loop lag and commands per minute over the last 15 minutes, with a table view. Most used commands, resource meters, recent commands, errors and alerts, runtime details, shards. |
| **Bot link** | Connection state, pairing codes, unpairing, and the list of what the bot allows. |
| **Users and roles** | Dashboard accounts, roles and their permissions, Discord login settings. |
| **Audit log** | What was done on the website, and what the bot ran or refused. The two logs are kept separately, on the web host and on the bot host. |
| **Sessions** | Browsers that are logged in. End one, or log out everywhere else. |
| **Account** | Password, two-factor login with recovery codes. |

### Running commands

A command started from the dashboard runs in the channel you pick. The bot posts the command there
first, with the name of the dashboard user, so the server always sees what was run and by whom.

You choose whose rights the command runs with:

- **An ordinary member** (capability `commands.run`). The command's own permission checks apply as
  they would for a member without any role, so anything restricted is refused by the command itself.
- **The bot owner** (capability `commands.owner`, off by default, needs approval by default). The
  command runs as if the bot owner had typed it.

Options are filled in order. Buttons and menus in an answer are used in Discord; commands that need
an uploaded file can only be run there.

### Files and the editor

Files can be read up to `[dashboard] max_file_kb` (1 MB by default) and travel in pieces of 768 KB,
so larger limits work too. Saving checks that nobody changed the file on the bot since you opened
it. With **Reload after saving** the bot reloads the extension the file belongs to; with hot reload
on, the bot also picks up changes made outside the dashboard within a few seconds.

Every save, upload, rename and delete needs `files.write` (off by default, needs approval by
default). "Approve for 15 minutes" in the Discord message covers a working session. Creating an empty
folder and the single pieces of an upload do not ask; the final step of the upload does.

### Configuration

The website can never change `[dashboard]`, `[modules] dashboard` or `bot.owner_ids`, neither in the
form nor in the file. `.env` cannot be opened. Reading the configuration needs `config` but does not
ask for approval; saving does. If the bot cannot use a saved `config.toml`, it puts the previous
file back. Intents, sharding, the database path and logging need a restart to change.

### Servers, backups and leaving

Changing a prefix or a command restriction needs `settings`. Creating, comparing, previewing,
pinning and deleting backups need `backups`; restoring needs `backups.restore` (off by default,
needs approval by default). Run **Preview a restore** first: it lists every change without making
it. Leaving a server needs `guilds.leave` and the exact server name.

While a restore runs, the page shows its current step. With **Update existing items** on, only channels
and categories that differ from the backup are changed. Discord allows two name or topic changes
per channel in ten minutes; a change it holds back is skipped and listed in the report, and a
later restore picks it up.

### Tickets and transcripts

When a ticket of the **Support tickets** automation is closed, in Discord or from the dashboard,
the bot saves a transcript first: every message with its author, time, cards and attachment
links, kept under `data/tickets/` (the newest 500 per server). Set **Send transcripts to** to also
post each transcript as a text file in a channel. Turn **Save a transcript on close** off in the
automation's settings if you do not want transcripts. Reading transcripts needs `chat.read`; closing a
ticket and deleting a transcript need `automations`.

### Panels for extensions

Extensions can add their own pages under **Panels**: statistics, tables, lists, forms and buttons.
They show up as soon as the extension loads and go away when it is unloaded. Viewing a panel needs
`view` by default, and its buttons and forms need `extensions`, so the same switches, approvals and
roles apply as everywhere else. An extension cannot send HTML or JavaScript to the browser.

Writing one: [docs/dev/dashboard-panels.md](../dev/dashboard-panels.md).

### Lost owner password

Run `/dashboard recover` in Discord as the bot owner. The bot sends a code to you in private and
tells the website, over the signed link, to accept it for 15 minutes. Open `recover.php` on the
website, enter the code, the owner account's user name and a new password; you can also turn off
two-factor login for that account. The code is never part of a link.

### Chat permissions

Chat follows the bot's own Discord permissions per channel: it lists only channels the bot can see
and offers only what the bot may do there. Deleting other members' messages and pinning need the
capability `chat.moderate`, which is off by default. Mentions of `@everyone` and roles in messages
sent from the dashboard do not ping, as with every message the bot sends.

### Keyboard

| Keys | Does |
|---|---|
| `Ctrl+K` | Command palette: every page, sub-pages, servers, extension panels and quick actions |
| `?` | The list of shortcuts |
| `/` | Search on the current page |
| `g` then a letter | Go to a page: `o` overview, `l` logs, `y` system, `c` chat, `m` commands, `s` servers, `a` automations, `t` tickets, `f` files, `e` extensions, `d` database, `p` panels, `k` configuration, `b` bot link, `u` users, `r` audit log |
| `Ctrl+S` | Save in the file and configuration editors |

The theme follows your system and can be switched in the top bar. The layout works on phones.

### Look and motion

The dashboard has a dark and a light theme, a moving background that ripples when the bot runs a
command, receives a chat message or logs an error, and short animations when pages, lists and
numbers change. All of it is optional for the browser:

- With "reduce motion" switched on in the system settings, animations become instant changes and
  the background is a still image.
- With data saver on, on devices with 2 GB of memory or less, or without WebGL 2, the background is
  off and a plain gradient is shown.
- The background pauses while the tab is hidden and renders at reduced resolution, 30 frames per
  second.
- Chromium-based browsers also bend the page behind the edges of the side rail, the command
  palette and dialogs. Other browsers show the same panels with a frosted blur.

## Commands

All of them are for the bot owner. Answers that contain a secret are sent privately.

| Command | Purpose |
|---|---|
| `/dashboard status` | Link state, last contact, round trip time, capabilities |
| `/dashboard export` | Build the folder to upload, with a fresh setup key |
| `/dashboard pair <url> <code>` | Connect the bot to an uploaded dashboard |
| `/dashboard capabilities` | Choose what the website may do and what needs your approval |
| `/dashboard lock [locked]` | Switch the link to view-only at once, or back |
| `/dashboard unpair` | Disconnect and forget the shared secret |
| `/dashboard recover` | Get a code to reset a lost owner password on the website |
| `/dashboard audit` | Actions the dashboard asked the bot to run, with the outcome |

## Bot-side settings

Everything in `[dashboard]` is enforced by the bot. It cannot be changed from the website.

| Key | Default | Meaning |
|---|---|---|
| `capabilities` | the safe set, see the [table below](#capabilities) | What the website may ask for |
| `approval` | all dangerous capabilities | These wait for the owner to press Approve in a Discord DM |
| `approval_timeout` | `300` | Seconds until an unanswered approval request is denied |
| `file_roots` | `["extensions"]` | Folders the file manager may open, relative to the bot folder |
| `max_file_kb` | `1024` | Largest file the dashboard may read or write |
| `idle_interval` | `45` | Seconds between check-ins while nobody has the dashboard open |
| `locked` | `false` | `true` = view only |

`/dashboard capabilities` and `/dashboard lock` store their changes as runtime overrides, like
`/fw config set`.

## Capabilities

Every action on the website belongs to a capability. The bot runs an action only when its
capability is listed in `[dashboard] capabilities`; the website's roles can narrow that further,
never widen it. Change the list with `/dashboard capabilities` in Discord (bot owner only).

| Capability | Covers | Default |
|---|---|---|
| `view` | status, statistics, lists | on |
| `logs` | live log tail | on |
| `chat.read` | read channels the bot can see | on |
| `chat.send` | send, edit and delete the bot's own messages, react | on |
| `commands.run` | run commands with the rights of an ordinary member: the command's own checks refuse anything else | on |
| `extensions` | load, unload, reload | on |
| `files.read` | read files inside the allowed folders | on |
| `automations`, `scheduler`, `settings`, `backups`, `presence` | manage those systems | on |
| `chat.moderate` | delete other members' messages, pin | off |
| `database` | read-only database browser | off |
| `files.write` | create, change, rename, delete files | off, needs approval |
| `config` | change `config.toml` and runtime overrides | off, needs approval |
| `marketplace` | install extensions and Python packages | off, needs approval |
| `commands.owner` | run commands with the rights of the bot owner | off, needs approval |
| `backups.restore` | restore a server backup | off, needs approval |
| `guilds.leave` | make the bot leave a server | off, needs approval |
| `system` | shut the bot down | off, needs approval |

A capability listed in `[dashboard] approval` waits for the bot owner to press **Approve** in a
Discord DM. The message names the dashboard user, the action and a summary. **Approve for 15
minutes** covers further actions of the same capability by the same user.

## Users, roles and logins

Setup creates the first **Owner**. Owners add more users under **Users and roles**.

| Role | May |
|---|---|
| Owner | Everything, including users, roles and the bot link |
| Admin | Every bot capability and the audit logs |
| Operator | Day-to-day work: view, logs, chat, commands, extensions, automations, scheduler, settings, backups, presence |
| Viewer | Status and logs |

Owners can change these roles (except Owner) and add their own. A role never gives more than the
bot allows: if `files.write` is off on the bot, no role can write files.

**Two-factor login.** Each user can turn it on under **Account**. It works with any authenticator
app (TOTP). Eight recovery codes are shown once.

**Discord login** is optional. An owner enters a Discord application's client ID and secret under
**Users and roles → Discord login** and adds the shown redirect address to the application. After
that, users whose Discord ID was added to their account can log in with Discord, and the bot's
owners can always log in and receive an Owner account.

Login attempts are rate limited per address and per user name.

## Hosting notes

- **Live updates** hold a request open for up to 20 seconds, so a change shows up within about a
  second. While somebody watches, this uses one PHP process for the bot and one per open tab.
- **Process limits.** If your host allows very few PHP processes at once, set `'hold' => 0` in
  `data/config.php`. The bot and the browser then poll every two seconds instead.
- **Idle.** When nobody has the dashboard open the bot sends a short status report every
  `idle_interval` seconds and keeps one light request open, so the first page view is current.
- **Compression.** Reports are gzip-compressed when the host has zlib.
- **Reverse proxies.** If the site sits behind a proxy or CDN and rate limits hit everyone at once,
  set `'ip_header' => 'HTTP_X_FORWARDED_FOR'` (or your proxy's header) in `data/config.php`.
- **Updating.** Run `/dashboard export` again and upload the files over the old ones, including
  `.htaccess`. Keep the `data` folder; it holds the configuration and, with SQLite, the database.
- **Caches and CDNs.** Every link to a style or script carries the time the file last changed, so
  an updated dashboard is loaded fresh even behind Cloudflare or another cache, with nothing to
  purge. For scripts this uses an import map, which all current browsers support (Chrome 89,
  Firefox 108, Safari 16.4). Older browsers load the plain addresses and may show a stale mix for
  as long as the cache in front keeps them.
- **Moving or removing.** Run `/dashboard unpair`, then delete the folder and, with MySQL, the
  tables that start with `zd_`.

## Troubleshooting

| Problem | What to do |
|---|---|
| "The pairing code is wrong or has expired" | Codes last 10 minutes and work once. Create a new one under **Bot link**. |
| "The dashboard must use HTTPS" | The bot refuses plain HTTP except for `127.0.0.1` and `localhost`. Enable HTTPS on the host. |
| "No dashboard was found at that address" | The URL must point at the folder that contains `index.php`. |
| The bot shows as offline | Check that the bot runs and that `/dashboard status` says Connected. The status names the last error. |
| "The website no longer accepts this bot's signature" | The website was reinstalled or unpaired. Create a pairing code and run `/dashboard pair` again. |
| Setup says the private folders can be opened | On Apache or LiteSpeed upload the `.htaccess` files and allow overrides. On nginx add the rules from `nginx.example.conf`. |
| The page looks broken or old after an update | Check that every file was uploaded, including the `app` folder. If the site was installed before links carried a change time, purge the cache of your CDN once (Cloudflare: Caching, Purge everything) and reload. |
| An action says it is switched off | Enable its capability with `/dashboard capabilities`. |
| An action waits for approval | The bot owner received a DM with Approve and Deny. The bot must be allowed to DM its owner. |
| The clock differs | Requests more than 60 seconds off are refused. The bot corrects for the website's clock on its own; if it cannot, fix the time on the bot host. |
| The only owner lost the password | With Discord login enabled, a bot owner can log in with Discord and reset it. Without it, remove the `data` folder contents (and the `zd_` tables) and run setup again. |

## Security in short

- The bot only connects out to the website over HTTPS. The website never connects to the bot.
- Pairing derives a shared secret on both sides; neither the code nor the secret travels.
- Every request and every answer is signed and checked for age and replays.
- The bot enforces capabilities, approvals, a file sandbox (only `[dashboard] file_roots`, never
  `.env`, databases or keys), protected settings and an audit log, whatever the website asks.
- The website uses Argon2id passwords, optional TOTP, strict sessions, CSRF checks and a strict
  Content Security Policy.
- If the web host is ever compromised, an attacker is still limited to the enabled capabilities,
  cannot pass an approval and leaves a trail on the bot host. Run `/dashboard lock`, then
  `/dashboard unpair`, and pair again after cleaning the host.

The full protocol and threat model: [docs/dev/dashboard-protocol.md](../dev/dashboard-protocol.md).
Running the website locally and changing it: [docs/dev/dashboard-internals.md](../dev/dashboard-internals.md).
