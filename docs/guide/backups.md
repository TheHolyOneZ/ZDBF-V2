# Backup and restore

Snapshots of a whole server that you can compare and restore, in parts or completely. Backup
commands need the **Administrator** permission.

- [What a backup contains](#what-a-backup-contains)
- [Create and look at backups](#create-and-look-at-backups)
- [Restore](#restore)
- [Compare](#compare)
- [Automatic backups and limits](#automatic-backups-and-limits)
- [For the bot owner](#for-the-bot-owner)
- [Good to know](#good-to-know)

## What a backup contains

| Part | Details |
|---|---|
| Roles | Name, colour, icon, permissions, position, hoist, mentionable |
| Categories | With their permission overwrites |
| Channels | Text, announcement, voice, forum (with tags) and stage channels, topic, slowmode, NSFW flag, permission overwrites |
| Emojis, Stickers | Images and names (emojis managed by an integration are left out) |
| Server settings | Name, description, verification level, notification and content filter settings, AFK, system, rules and updates channels, locale |
| Icon and banner | The images |
| Member roles | Which member had which roles |
| Bot settings | The bot's prefix, mention prefix and command role restrictions for this server |

Messages are not backed up.

Backups are stored compressed under `data/backups/<server id>/`, each with a checksum.

## Create and look at backups

| Command | Does |
|---|---|
| `/backup` | An overview of this server's backups with buttons |
| `/backup create [label]` | Take a backup now |
| `/backup list` | Every backup of this server |
| `/backup view <backup_id>` | What a backup holds |
| `/backup verify <backup_id>` | Check its checksum |
| `/backup note <backup_id> <note>` | Attach a note |
| `/backup pin <backup_id>` | Pin or unpin. Pinned backups are never removed by rotation or retention. |
| `/backup delete <backup_id>` | Delete one |
| `/backup audit` | Who created, restored or deleted backups |

Backup IDs autocomplete when you type them in a slash command.

## Restore

`/backup restore <backup_id>` opens a restore panel:

1. **Choose the parts** to restore (roles, channels, emojis, member roles...). Everything is
   selected by default.
2. **Update existing: on or off.** On: items that already exist are changed to match the backup.
   Off: only missing items are created.
3. **Sync member roles: on or off.** Gives members back the roles they had in the backup.
4. **Preview (dry run)** lists every change without making any. Always run it first.
5. **Restore**, then **Confirm restore**. Progress is shown live and a report follows with what was
   created, updated, skipped and why.

A restore creates and updates. It does not delete roles or channels that are not in the backup.

## Compare

`/backup diff <backup_id>` compares a backup with the server as it is now. Add a second backup ID
(`other`) to compare two backups. The result lists added, removed and changed roles, channels
and settings.

## Automatic backups and limits

`/backup schedule <hours>` takes a backup of this server every N hours (1 to 720, `0` turns it off).

These limits are set by the bot host in `[backup]`:

| Key | Default | Meaning |
|---|---|---|
| `max_per_guild` | `25` | Backups kept per server. The oldest unpinned one is removed when a new one is made. |
| `cooldown_seconds` | `300` | Time between two manual backups in one server |
| `auto_interval_hours` | `0` | Default automatic interval for servers that did not choose one (`0` = off) |
| `retention_days` | `0` | Remove unpinned backups older than this (`0` = keep) |

## For the bot owner

| Command | Does |
|---|---|
| `/backup export <backup_id>` | Download a backup as JSON |
| `/backup stats` | Backup statistics across all servers |

## Good to know

- **The bot's role must be high enough.** The bot can only create and edit roles below its own
  highest role, and needs Manage Roles, Manage Channels, Manage Emojis and Stickers and Manage
  Server for a full restore. Missing permissions are listed in the report, nothing breaks.
- **Discord rate limits.** Discord allows two name or topic changes per channel in ten minutes. A
  change it holds back is skipped and named in the report; running the restore again later picks
  it up.
- **Restoring into a new server.** Roles and categories are matched by ID first, then by name, so
  a backup can be restored into a fresh server to rebuild its layout.
- **In the dashboard.** The **Servers** page of the [web dashboard](dashboard.md) creates, compares,
  previews, restores, pins and deletes backups too. Restoring there needs the `backups.restore`
  capability and the bot owner's approval by default.
