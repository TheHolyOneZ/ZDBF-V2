# Database and storage

ZDBF keeps its data in one SQLite file, `data/zdbf.db`, reached through `bot.db`. Extensions use
the same database: key/value storage for small things, their own tables for real data, and an
atomic file handler for JSON files.

- [Which storage to use](#which-storage-to-use)
- [Key/value storage](#keyvalue-storage)
- [Queries](#queries)
- [Transactions](#transactions)
- [Your own tables: migrations](#your-own-tables-migrations)
- [Atomic files](#atomic-files)
- [How the database is protected](#how-the-database-is-protected)
- [Framework tables and core migrations](#framework-tables-and-core-migrations)
- [Good practice](#good-practice)

## Which storage to use

| You need | Use |
|---|---|
| A setting per server (a channel, a toggle, a small dict) | `bot.db.get_setting` / `set_setting` |
| A global value (last run, a counter, a cache) | `bot.db.kv_get` / `kv_set` |
| Many rows you query, sort or count (items, logs, scores) | Your own table, created by a migration |
| A file other tools read, or a large document | `global_file_handler.atomic_write_json` |

## Key/value storage

Values are stored as JSON, so anything `json.dumps` accepts works: numbers, strings, lists, dicts,
`True`/`False`, `None`.

```python
await bot.db.set_setting(guild.id, "shop.channel", channel.id)
channel_id = await bot.db.get_setting(guild.id, "shop.channel")          # None if unset
enabled = await bot.db.get_setting(guild.id, "shop.enabled", False)      # with a default
await bot.db.delete_setting(guild.id, "shop.channel")                    # True if it existed
everything = await bot.db.all_settings(guild.id)                         # {key: value}

await bot.db.kv_set("shop.restocked_at", "2026-11-12T09:00:00Z")
when = await bot.db.kv_get("shop.restocked_at")
await bot.db.kv_delete("shop.restocked_at")
```

Prefix every key with your extension's name. Server [backups](../guide/backups.md) do not include
extension settings; they hold the server's Discord layout and the bot's prefix and command
restrictions.

## Queries

```python
rows = await bot.db.fetchall("SELECT name, price FROM shop_items WHERE guild_id = ? ORDER BY price", (guild.id,))
for row in rows:
    print(row["name"], row["price"])          # rows work by name and by index

row = await bot.db.fetchone("SELECT * FROM shop_items WHERE id = ?", (item_id,))
count = await bot.db.fetchval("SELECT COUNT(*) FROM shop_items WHERE guild_id = ?", (guild.id,), default=0)

changed = await bot.db.execute("UPDATE shop_items SET price = ? WHERE id = ?", (price, item_id))   # rowcount
await bot.db.executemany("INSERT INTO shop_items (guild_id, name, price) VALUES (?, ?, ?)", rows)
```

Parameters can be a sequence (`?`) or a dict (`:name`). Always pass values as parameters, never
format them into the SQL string.

Reads run on a separate read-only connection that only sees committed data, so a long read never
blocks writes. Each `execute` is its own atomic commit. If the database is busy, a statement is
retried a few times before it fails.

## Transactions

Group writes that must succeed or fail together:

```python
async with bot.db.transaction() as conn:
    await conn.execute("UPDATE wallets SET coins = coins - ? WHERE user_id = ?", (price, buyer))
    await conn.execute("UPDATE wallets SET coins = coins + ? WHERE user_id = ?", (price, seller))
```

The block commits when it ends and rolls back if it raises. Inside it, `bot.db.execute`,
`fetchone` and the other helpers use the same connection and see your uncommitted changes, and a
nested `transaction()` joins the outer one. Keep transactions short: writes from the rest of the
bot wait until yours ends. Do not `await` Discord calls inside one.

## Your own tables: migrations

Create a file in the `migrations/` folder next to `config.toml`, named `NNN_name.py`:

```python
# migrations/010_shop.py
description = "shop tables"


async def up(db):
    await db.conn.execute("""
        CREATE TABLE IF NOT EXISTS shop_items (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name     TEXT    NOT NULL,
            price    INTEGER NOT NULL DEFAULT 0
        )""")
    await db.conn.execute("CREATE INDEX IF NOT EXISTS idx_shop_items_guild ON shop_items(guild_id)")
```

- Migrations run in number order on every start, before extensions load. `db` is `bot.db`.
- A database backup is taken before the first pending migration runs.
- Each migration is recorded in `_schema_migrations`. A successful one never runs again; a failed
  one stops the run, sends an alert, and is retried on the next start.
- `/diag migrations` shows the status, `/diag migrate` runs pending ones without a restart.
- To change a table later, add a new migration (`011_shop_add_stock.py`). Never edit one that has
  already run on someone's bot.
- Use `IF NOT EXISTS` so a migration is safe to run against a database that already has the table.
- Pick a number range for your extension (for example 100 to 199) so it does not clash with
  others in the same folder.

User migrations are run by the **diagnostics** module. If the bot owner switched it off, create
your tables with `CREATE TABLE IF NOT EXISTS` in `cog_load` instead, or as well.

## Atomic files

`global_file_handler` writes files so that a crash never leaves a half-written file: it writes a
temporary file, flushes it to disk and renames it into place, with a lock per path and a read cache.

```python
from zdbf.core.storage import global_file_handler

await global_file_handler.atomic_write_json("data/shop/catalogue.json", data)
data = await global_file_handler.atomic_read_json("data/shop/catalogue.json") or {}

await global_file_handler.atomic_write("data/shop/notes.txt", "text")
text = await global_file_handler.atomic_read("data/shop/notes.txt")       # None if missing

global_file_handler.invalidate_cache("data/shop/catalogue.json")          # after an outside change
```

Reads are cached for 5 minutes. Pass `use_cache=False` to read from disk, and call
`invalidate_cache` if something other than the handler changes the file. Parent folders are created
for you. Keep your files under `data/<your extension>/`.

V1 code that imports `from atomic_file_system import global_file_handler` gets the same object.

## How the database is protected

- **One writer.** All writes go through one connection behind a lock, so two tasks never write at
  the same time.
- **WAL mode** with `synchronous=NORMAL`, `foreign_keys=ON` and a busy timeout.
- **Checked on start.** `PRAGMA quick_check` runs on every start. A damaged file is moved aside as
  `zdbf.corrupt-<time>.db` and the newest healthy backup is restored, with a critical alert.
- **Backups.** Rolling backups in `data/db_backups/` (7 kept, one per 24 hours by default), plus
  one before every core or user migration.
- **Restores only on start.** `/fw db` schedules a restore that is applied before the database is
  opened on the next start; the replaced file is kept.

## Framework tables and core migrations

Tables the framework owns. Read them if you need to, but write to them through the APIs above.

| Table | Contents |
|---|---|
| `global_kv` | `kv_get` / `kv_set` |
| `guild_settings` | `get_setting` / `set_setting`, including prefixes |
| `command_permissions` | Role requirements from `/settings permissions` |
| `command_stats` | Command usage counts |
| `scheduled_tasks` | Scheduler tasks |
| `automations`, `automation_state` | Automations and their state (XP, counters, cooldowns) |
| `_zdbf_schema` | Applied core migrations |
| `_schema_migrations` | Applied user migrations |

Framework changes to the schema go into `CORE_MIGRATIONS` in `zdbf/core/migrations/__init__.py`
as a new `(version, name, sql)` entry. They run inside one transaction each, in version order,
right after the database opens.

## Good practice

- **Index by `guild_id`** in your own tables and filter on it.
- **Clean up when you want to.** The bot keeps a server's data when it leaves the server, so that
  re-inviting it restores everything. If your extension should forget a server, listen to the
  `guild_left` event and delete its rows.
- **Name secret columns clearly.** The dashboard's read-only database browser hides columns whose
  names contain `token`, `secret`, `password`, `passwd`, `api_key` or `apikey`.
- **Large blobs** (images, archives) belong in files under `data/`, not in the database.
- **Testing.** `Database(":memory:")` gives an in-memory database for unit tests. Call
  `await db.connect()` first and `await db.close()` at the end.
