# Writing extensions

An extension is a Python file (or package) in `extensions/` with an
`async def setup(bot)` function - a normal discord.py extension. ZDBF adds a
UI kit, storage, hooks, a scheduler and metadata checks on top.

```python
from discord.ext import commands
from zdbf.ui import cards

__version__ = "1.0.0"

class Hello(commands.Cog):
    emoji = "👋"

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(description="Say hello")
    async def hello(self, ctx):
        await ctx.send(view=cards.success("Hello!", f"Hi {ctx.author.mention}"))

async def setup(bot):
    await bot.add_cog(Hello(bot))
```

* Files load on start (unless listed in `[extensions].blacklist`) and **hot-reload** when saved.
  A broken edit is rolled back - the previous version keeps running.
* Manage them with `/ext list|load|unload|reload|info`.
* Use **hybrid commands** so they work as `/slash` and `!prefix`. Put several commands in a
  `hybrid_group` - Discord allows only 100 top-level slash commands per bot.
* If extensions together go over 100, nothing breaks: framework commands keep their slots,
  then extensions in load order. Hybrid commands over the limit stay available with the
  prefix; pure `app_commands` get a prefix fallback automatically. `/diag commands` lists
  what was demoted, and slots are refilled when an extension is unloaded.

## Metadata

Module-level dunders are read **without importing** the file, so problems are
reported before the extension loads:

```python
__version__ = "1.2.0"
__author__ = "You"
__description__ = "Economy system"
__dependencies__ = {"bank": ">=1.0"}     # or ["bank"]; operators: >= <= > < == != ~=
__conflicts__ = ["old_economy"]
__provides_hooks__ = ["economy_transaction"]
__listens_to_hooks__ = ["command_executed"]
```

Blocked extensions show up in `/ext list` and `/plugins validate`. Enforcement can be
relaxed with `/plugins enforce`.

## Components V2 UI kit (`zdbf.ui`)

```python
from zdbf.ui import BaseView, Paginator, button, cards, confirm, row

# static messages
await ctx.send(view=cards.success("Saved", "All done."))       # also info / warning / error
await ctx.send(view=cards.static(cards.card(
    "Profile", cards.kv({"Level": 5, "XP": "1,250"}), cards.sep(), "Some text",
    emoji="⭐", accent="gold", thumbnail=ctx.author.display_avatar.url, foot="footer")))

# paginated lists
await Paginator.from_lines(lines, per_page=10, title="Leaderboard", emoji="🏆").send(ctx)

# confirmation
view = await confirm(ctx, "Delete everything?", "This cannot be undone.")
if view.value:
    ...

# interactive views: override build(), call refresh() after changes
class Counter(BaseView):
    def __init__(self, author_id):
        super().__init__(author_id=author_id)   # only this user (or an owner) can click
        self.n = 0

    def build(self):
        self.clear_items()
        box = cards.card("Counter", f"Clicked **{self.n}** times")

        async def plus(interaction):
            self.n += 1
            await self.refresh(interaction)

        box.add_item(row(button("+1", plus)))
        self.add_item(box)

await Counter(ctx.author.id).send(ctx)
```

Views disable their components on timeout and answer callback errors with an
ephemeral error card. `zdbf.ui.FormModal` builds modals from `FormField`s.

## Storage

```python
# per-guild key/value (JSON values)
await bot.db.set_setting(guild.id, "myext.enabled", True)
await bot.db.get_setting(guild.id, "myext.enabled", False)

# global key/value
await bot.db.kv_set("myext.state", {"runs": 3})

# your own tables - add a migration file: migrations/002_myext.py
description = "myext tables"
async def up(db):
    await db.conn.execute("CREATE TABLE IF NOT EXISTS myext_items (guild_id INTEGER, name TEXT)")

# then query
rows = await bot.db.fetchall("SELECT name FROM myext_items WHERE guild_id = ?", (guild.id,))
await bot.db.execute("INSERT INTO myext_items VALUES (?, ?)", (guild.id, "x"))
async with bot.db.transaction() as conn:   # several writes, one commit
    ...

# atomic JSON files
from zdbf.core.storage import global_file_handler
await global_file_handler.atomic_write_json("data/myext.json", data)
data = await global_file_handler.atomic_read_json("data/myext.json") or {}
```

User migrations run automatically on start; check them with `/diag migrations`.

## Event hooks

```python
async def cog_load(self):
    self.bot.register_hook("command_executed", self.on_cmd, priority=5)

async def on_cmd(self, bot, command_name, author, guild, **kwargs):
    ...

await self.bot.emit_hook("economy_transaction", user=user, amount=50)   # your own events
```

Built-in events: `bot_ready`, `guild_joined`, `guild_left`, `command_executed`,
`command_error`, `extension_loaded`, `extension_unloaded`, `extension_reloaded`,
`scheduled_task`, `cluster_broadcast`. Hooks run in a background worker with a
10 s timeout; a hook failing 5 times in 5 minutes is paused by a circuit breaker.
Hooks registered by a module are removed automatically when it unloads.

## Scheduler

```python
scheduler = bot.get_cog("Task Scheduler")
task_id = await scheduler.create_task_programmatic(
    task_name="weekly_report", cron_expression="0 9 * * mon", task_type="hook",
    guild_id=guild.id, payload={"hook_name": "weekly_report", "data": {}})
await scheduler.delete_task_programmatic(task_id)
```

Task types: `message` (`payload={"content": "...", "title": "..."}`), `hook`, `log`.
Cron uses the timezone in `[scheduler].timezone`.

## Configuration

Read your own table from `config.toml`:

```toml
[weather]
api_key = "..."
interval = 300
```

```python
key = bot.config.get("weather.api_key")
await bot.config.set("weather.interval", 600)   # runtime override, config.toml untouched

validator = bot.get_cog("Config Validator")      # optional: validated by /fw config validate
validator.register_extension_schema("weather", {"weather": {"type": dict, "children": {
    "api_key": {"type": str, "required": True},
    "interval": {"type": int, "min": 60, "max": 3600}}}})
```

## Permissions

```python
from zdbf.core.permissions import owner_only, admin_or_owner, guild_owner_or_owner

@commands.hybrid_command()
@owner_only()
async def secret(self, ctx): ...
```

Server admins can restrict any command to roles with `/settings permissions add`.

## Alerts

```python
await bot.alerts.send("myext", "Something needs attention", "warning")
```

Routed to the channel set with `/fw alerts` (per system, or the `default` channel).

## V1 compatibility

V1 extensions run unchanged: `bot.register_hook / emit_hook / register_plugin`,
`bot.db.get_guild_prefix`, `bot.db._get_guild_connection(guild_id)` (per-guild
SQLite files), `bot.db.conn`, `bot.config.get("prefix")`, `bot.bot_owner_id`,
`from atomic_file_system import global_file_handler`, and the cogs
`Task Scheduler`, `Database Migrations` and `Config Validator`.
Embeds still work - Components V2 is recommended for new code.
