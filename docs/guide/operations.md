# Running the bot: health, alerts, data and scale

Everything a bot host needs once the bot runs: checking its health, getting alerts, looking after
the database and logs, and growing to many servers. All commands on this page are for the bot owner.

- [Health and diagnostics](#health-and-diagnostics)
- [Alerts](#alerts)
- [Errors](#errors)
- [The database](#the-database)
- [Logs](#logs)
- [Maintenance](#maintenance)
- [Slash command budget](#slash-command-budget)
- [Sharding](#sharding)
- [Clusters](#clusters)

## Health and diagnostics

| Command | Shows |
|---|---|
| `/diag overview` | Health status (healthy, degraded or critical), event-loop lag, error rate, latency and memory |
| `/diag history` | Past health checks with trend lines |
| `/diag errors` | Recent command errors with their reference codes |
| `/diag commands` | The slash command budget, see below |
| `/diag migrations`, `/diag migrate` | Database migrations of extensions, and applying pending ones |
| `/fw integrity` | One full check: configuration, database integrity, writable folders, atomic storage, the event hook worker, failed extensions, slash budget, intents, latency and disk space |
| `/ping` | Gateway, API and database latency (everyone) |
| `/stats` | Uptime, servers, members, commands, errors, memory, shards (everyone) |

A health check runs every 5 minutes. The thresholds are in `[diagnostics]`:

| Key | Default | Meaning |
|---|---|---|
| `loop_lag_threshold_ms` | `500` | Event-loop lag that counts as degraded |
| `health_interval_minutes` | `5` | Time between checks |
| `error_rate_warn_percent` | `10.0` | Share of commands that crashed in the last hour before health is degraded (twice this is critical) |
| `error_rate_min_commands` | `20` | The error rate only counts once this many commands ran in the last hour, so one crash on a quiet bot does not flip the status |

## Alerts

Each system sends its alerts to a channel you choose:

```
/fw alerts errors #bot-errors
/fw alerts backup #backups
/fw alerts default #bot-alerts
```

Systems: `errors`, `diagnostics`, `eventhooks`, `plugins`, `extensions`, `shards`, `cluster`,
`backup`, `scheduler`, `automations`, `marketplace`, `database`, `dashboard`. A system without its
own channel uses `default`. Run `/fw alerts` without options to see the current routing.

Typical alerts: a failed hot reload, an extension blocked by a missing dependency, an automation
switched off after repeated failures, a circuit breaker opening, a shard going down and coming
back, a scheduled task failing, the database being recovered.

## Errors

When a command fails unexpectedly, the member sees a short card with a reference code. The full
traceback goes to `logs/errors.log` and to the `errors` alert channel under the same code, so you
can match a user's report to the cause. `/diag errors` lists recent ones.

Expected problems, such as missing permissions, a wrong option or a cooldown, are explained to the
member directly. They are not errors: they do not appear in `/diag errors` and do not count toward
the error rate or the health status. `/stats` and `/diag overview` show them separately as
"Refused".

## The database

All data lives in one SQLite file, `data/zdbf.db` (`[database] path`).

- **Safe writes.** Writes go through one connection and are committed atomically. Reads use a
  second, read-only connection that only sees committed data.
- **Checked on every start.** A damaged file is moved aside as `zdbf.corrupt-<time>.db` and the
  newest healthy backup from `data/db_backups/` is restored automatically, with a critical alert.
- **Rolling backups.** One every 24 hours, 7 kept (`[maintenance] db_backup_interval_hours` and
  `db_backup_keep`), plus one before every migration.
- **`/fw db`** shows statistics and has buttons to take a backup, run a quick or full integrity
  check, and schedule a restore from any backup. A restore is applied on the **next start**, never
  while the bot runs; the replaced file is kept as `zdbf.replaced-<time>.db`.

To back up the bot by hand, stop it and copy `data/`, `config.toml`, `.env` and `extensions/`.

## Logs

Logs go to `logs/` (`[logging] directory`):

| File | Contents |
|---|---|
| `zdbf.log` | Everything from INFO up, or from DEBUG with `level = "DEBUG"` |
| `errors.log` | Errors and tracebacks only |

Files rotate at `max_bytes` (10 MB), `backup_count` (5) old files are kept per log, and files
older than `retention_days` (30) are removed. Set `[logging] level = "DEBUG"` for more detail.

The **Logs** page of the [web dashboard](dashboard.md) shows the log live, with tokens and secrets
hidden.

## Maintenance

Every hour the bot clears expired caches, removes old log files and `__pycache__` folders in
`extensions/` (`[maintenance] clean_pycache`), checkpoints and optimises the database, and takes the
rolling database backup when one is due. `/fw cleanup` does the same on demand, and `/fw cache`
shows the cache statistics.

## Slash command budget

Discord allows 100 top-level slash commands per bot. The framework uses 15 with the default
modules, 17 with the dashboard and cluster modules on. When extensions push the total over 100,
nothing breaks: framework commands keep their slots, then extensions in load
order. The rest stay available with the prefix. `/diag commands` shows which commands were moved,
and slots are refilled when an extension is unloaded.

Slash commands sync on start only when they changed, and again 10 seconds after an extension is
loaded or unloaded. `/fw sync` syncs by hand:

| Mode | Does |
|---|---|
| `changed` | Sync if anything changed (default) |
| `force` | Sync everything now |
| `server` | Copy all commands to this server: they appear at once, useful for testing |
| `clear-server` | Remove that copy again |

Owner-only groups (`/fw`, `/ext`, `/diag`...) can be synced only to your own servers with
`[bot] dev_guild_ids`. Either way they are hidden from members without Administrator and refuse
anyone who is not an owner.

## Sharding

Large bots (Discord requires it from 2,500 servers) split their connection into shards. ZDBF
shards automatically. To choose yourself, set `SHARD_COUNT` and, per process, `SHARD_IDS` in `.env`.

| Command | Shows |
|---|---|
| `/shard monitor` | An interactive per-shard overview |
| `/shard health` | Health of every shard |
| `/shard details <shard_id>` | Latency, uptime, reconnects and event throughput of one shard |
| `/shard alerts [channel] [threshold]` | Where shard alerts go and after how many failures (`[shards] alert_threshold`, default 3) |
| `/shard reset [shard_id]` | Reset the metrics |
| `/stats shards` | Latency and server count per shard (everyone) |

An alert is sent after the set number of consecutive failures, and again when the shard recovers.

## Clusters

A cluster runs the shards of one bot in several processes or on several machines, which talk to
each other over IPC.

1. Set `[modules] cluster = true` in `config.toml` on every process.
2. In each process's `.env` set the same `SHARD_IPC_SECRET` (at least 16 random characters),
   `SHARD_COUNT`, its own `SHARD_IDS` and a unique `SHARD_CLUSTER_NAME`.
3. Exactly one process uses `SHARD_IPC_MODE=server`, all others `client`.
   `SHARD_IPC_HOST` and `SHARD_IPC_PORT` say where the server listens (default `127.0.0.1:20000`).

| Command | Does |
|---|---|
| `/cluster status` | Every connected cluster |
| `/cluster ipc` | Connection diagnostics |
| `/cluster broadcast <message>` | Sends a message to every cluster, which extensions receive as the `cluster_broadcast` event |

Every IPC frame is signed with HMAC-SHA256 and checked for age and replays. Keep the IPC port on a
private network or behind a firewall all the same.
