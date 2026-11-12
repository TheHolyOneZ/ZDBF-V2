# Writing extensions

An extension is a Python file (or package) in `extensions/` with an `async def setup(bot)`
function: a normal [discord.py extension](https://discordpy.readthedocs.io/en/stable/ext/commands/extensions.html).
ZDBF loads it on start, reloads it when you save it, and gives it the framework's building blocks:
a Components V2 UI kit, storage, event hooks, the scheduler, alerts, config sections and a page in
the web dashboard.

- [Your first extension](#your-first-extension)
- [Files and packages](#files-and-packages)
- [Lifecycle and hot reload](#lifecycle-and-hot-reload)
- [Commands](#commands)
- [Metadata, dependencies and conflicts](#metadata-dependencies-and-conflicts)
- [Showing things in Discord](#showing-things-in-discord)
- [Storing data](#storing-data)
- [Reacting to events](#reacting-to-events)
- [Scheduled tasks](#scheduled-tasks)
- [Configuration](#configuration)
- [Permissions](#permissions)
- [Alerts](#alerts)
- [A page in the web dashboard](#a-page-in-the-web-dashboard)
- [Python packages](#python-packages)
- [V1 compatibility](#v1-compatibility)
- [Publishing on the marketplace](#publishing-on-the-marketplace)
- [Checklist](#checklist)

## Your first extension

Create `extensions/hello.py`:

```python
from discord.ext import commands

from zdbf.ui import cards

__version__ = "1.0.0"
__author__ = "You"
__description__ = "Says hello"


class Hello(commands.Cog, name="Hello"):
    """Friendly greetings."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(description="Say hello")
    async def hello(self, ctx: commands.Context):
        await ctx.send(view=cards.success("Hello!", f"Hi {ctx.author.mention}"))


async def setup(bot):
    await bot.add_cog(Hello(bot))
```

New files load on the next start. While the bot runs, load it once with `/ext load hello`;
after that every save reloads it within a few seconds. `/hello` and `!hello` both work, and the
cog's docstring becomes its category text in `/help`.

`extensions/example.py` is a larger example with an interactive counter, storage and a hook.

## Files and packages

| Layout | Module name | Reloads when |
|---|---|---|
| `extensions/hello.py` | `extensions.hello` | The file changes |
| `extensions/shop/__init__.py` (+ more files) | `extensions.shop` | Any `.py` file in the folder changes |

- Names starting with `_` or `.` are ignored, so `extensions/_helpers.py` can hold shared code.
- A file name with spaces is renamed to use underscores.
- `[extensions] blacklist` lists names that never auto-load.
- Inside a package, use relative imports (`from .models import Item`).

## Lifecycle and hot reload

1. **Before loading**, the metadata is read from the file *without importing it*, and
   dependencies and conflicts are checked. A blocked extension is not imported at all.
2. `setup(bot)` runs. Add your cogs here.
3. `cog_load()` of each cog runs. Register hooks, start tasks and open resources here.
4. The `extension_loaded` event fires and slash commands are re-synced 10 seconds later if they changed.

**Reloading** (`/ext reload`, or saving the file with `[extensions] hot_reload = true`) imports the
new version first. If that fails, with a syntax error or an exception in `setup`, the old version
stays loaded and keeps running, and the error goes to the log and the `extensions` alert channel.

**Unloading** runs `cog_unload()`, removes every hook registered from the module and every
dashboard panel it added, then fires `extension_unloaded`.

Clean up what you start:

```python
class Ticker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.task = None

    async def cog_load(self):
        self.task = asyncio.create_task(self.loop())

    async def cog_unload(self):
        if self.task:
            self.task.cancel()
```

Old-style extensions with a plain `def setup(bot)` that calls `bot.add_cog(...)` without `await`
still load: ZDBF runs them in a compatibility mode and notes it in the log. Write new ones with
`async def setup`.

## Commands

- **Use hybrid commands** (`@commands.hybrid_command`, `@commands.hybrid_group`) so they work as
  `/slash` and with the prefix. `ctx.send()` answers both.
- **Group related commands.** Discord allows 100 top-level slash commands per bot and the framework
  uses 15 to 17, depending on the modules. A group with ten subcommands costs one slot.
- **Over the limit nothing breaks.** Framework commands keep their slots, then extensions in load
  order. Hybrid commands over the limit stay available with the prefix; pure `app_commands` get a
  prefix fallback automatically. `/diag commands` shows what was moved.
- **Describe options** with `@app_commands.describe(...)` and add `description=` to every command:
  `/help` shows both, and the dashboard turns them into form labels.
- **Errors are handled for you.** An unexpected exception shows the user a reference code and logs
  the traceback. Raise `commands.CommandError("message")` or a check failure to show a clear message.
- **Cooldowns.** Commands without their own cooldown get the default from `[cooldowns]`. Add
  `@commands.cooldown(rate, per, commands.BucketType.user)` for your own.

```python
from discord import app_commands
from discord.ext import commands


class Shop(commands.Cog, name="Shop"):
    """Buy and sell items."""

    @commands.hybrid_group(name="shop", description="The server shop", fallback="browse")
    async def shop(self, ctx):
        ...

    @shop.command(name="buy", description="Buy an item")
    @app_commands.describe(item="What to buy", amount="How many")
    async def buy(self, ctx, item: str, amount: commands.Range[int, 1, 99] = 1):
        ...
```

## Metadata, dependencies and conflicts

Module-level variables, read before the file is imported:

```python
__version__ = "1.2.0"
__author__ = "You"
__description__ = "Economy system"
__dependencies__ = {"bank": ">=1.0"}     # or ["bank"]
__conflicts__ = ["old_economy"]
__provides_hooks__ = ["economy_transaction"]
__listens_to_hooks__ = ["command_executed"]
```

- Dependencies name other extensions by module name (the file name without `.py`) with an
  optional version range. Operators: `>=`, `<=`, `>`, `<`, `==`, `!=`, `~=`.
- Missing dependencies, version mismatches, cycles and conflicts block the load and are shown in
  `/ext list` and `/plugins validate <name>`. Enforcement can be relaxed with `/plugins enforce`.
- `/plugins dependencies` shows the tree, `/plugins info <name>` the metadata, `/plugins commands
  <name>` everything an extension adds.

## Showing things in Discord

Every reply in ZDBF is a Components V2 layout built with `zdbf.ui`:

```python
from zdbf.ui import Paginator, cards, confirm

await ctx.send(view=cards.success("Saved", "All done."))        # also info, warning, error

await ctx.send(view=cards.static(cards.card(
    "Profile",
    cards.kv({"Level": 5, "XP": "1,250"}),
    cards.sep(),
    "Some text",
    accent="gold", thumbnail=ctx.author.display_avatar.url, foot="Updated just now")))

await Paginator.from_lines(lines, per_page=10, title="Leaderboard").send(ctx)

view = await confirm(ctx, "Delete everything?", "This cannot be undone.")
if view.value:
    ...
```

Interactive views, modals, select menus and list-detail pages: [ui-kit.md](ui-kit.md).

Keep to the framework's look: status dots (🟢🟡🔴⚪) are fine, decorative emoji in titles are
shown only when the bot owner turns on `[ui] decorative_emoji` (pass them as `emoji=` and the kit
decides). Paginate anything that can grow.

## Storing data

```python
await bot.db.set_setting(guild.id, "shop.currency", "coins")       # per server
currency = await bot.db.get_setting(guild.id, "shop.currency", "coins")

await bot.db.kv_set("shop.last_restock", "2026-11-12")              # global
```

Values are stored as JSON. Prefix your keys with your extension's name. For real tables, add a
migration; for files, use the atomic file handler. Everything is in [database.md](database.md).

## Reacting to events

```python
async def cog_load(self):
    self.bot.register_hook("command_executed", self.on_command_used, priority=5)

async def on_command_used(self, bot, command_name, author, guild, **kwargs):
    ...

await self.bot.emit_hook("economy_transaction", user=user, amount=50)   # your own event
```

Hooks run in a background worker with a timeout and a circuit breaker, and are removed
automatically when your extension unloads. Normal discord.py listeners (`@commands.Cog.listener()`)
work as well. Built-in events and details: [hooks-and-events.md](hooks-and-events.md).

## Scheduled tasks

Create cron tasks from code through the scheduler module:

```python
scheduler = bot.get_cog("Task Scheduler")
if scheduler is not None:
    task_id = await scheduler.create_task_programmatic(
        task_name="weekly_report",
        cron_expression="0 9 * * mon",
        task_type="hook",
        guild_id=guild.id,
        payload={"hook_name": "weekly_report", "data": {"guild_id": guild.id}})
    ...
    await scheduler.delete_task_programmatic(task_id)
```

| `task_type` | `payload` | Also needs |
|---|---|---|
| `message` | `{"content": "...", "title": None}` | `channel_id=` |
| `hook` | `{"hook_name": "...", "data": {...}}` | a hook registered for `hook_name` |
| `log` | `{"message": "...", "level": "INFO"}` | |

`create_task_programmatic` returns the task ID, or `None` for an invalid cron expression or type.
Optional arguments: `channel_id`, `creator_id`, `max_runs`, `enabled`. A hook task calls your hook
with the `data` keys plus `_task_name` and `_task_id`. Times use `[scheduler] timezone`. Tasks are
stored in the database, so keep the ID (for example with `kv_set`) instead of creating a new task
on every load.

The scheduler is a module the bot owner can switch off, so check for `None`.

## Configuration

Give your extension its own table in `config.toml`:

```toml
[weather]
api_key = "..."
interval = 300
```

```python
key = bot.config.get("weather.api_key")
interval = bot.config.get("weather.interval", 300)
await bot.config.set("weather.interval", 600)     # runtime override, config.toml is not touched
```

`set` stores a runtime override in `data/config_overrides.json`, like `/fw config set`.
`/fw config unset weather.interval` removes it again.

Register a schema so `/fw config validate` checks your section:

```python
validator = bot.get_cog("Config Validator")
if validator is not None:
    validator.register_extension_schema("weather", {
        "weather": {"type": dict, "children": {
            "api_key": {"type": str, "required": True},
            "interval": {"type": int, "min": 60, "max": 3600},
            "units": {"type": str, "choices": ["metric", "imperial"]},
        }},
    })
```

Rule keys: `type`, `required`, `min`, `max`, `choices`, `children`. A schema cannot redefine a
framework section such as `[bot]`. Call `validator.unregister_extension_schema("weather")` in
`cog_unload`.

Secrets such as API keys can also go in `.env` and be read with `os.environ`.

## Permissions

```python
from zdbf.core.permissions import admin_or_owner, guild_owner_or_owner, owner_only


@commands.hybrid_command()
@owner_only()                 # bot owners only
async def secret(self, ctx): ...


@commands.hybrid_command()
@admin_or_owner()             # Manage Server, or a bot owner
async def configure(self, ctx): ...


@commands.hybrid_command()
@guild_owner_or_owner()       # the server owner, or a bot owner
async def nuke(self, ctx): ...
```

These checks also tell `/help` and the dashboard who may run a command. Standard discord.py
checks (`@commands.has_permissions(...)`, `@commands.guild_only()`) work too. On top of all
that, server admins can require roles for any command, including yours, with
`/settings permissions add`. Group checks apply to every subcommand.

## Alerts

```python
await bot.alerts.send("weather", "The weather API is not answering", "warning")
```

Levels: `info`, `success`, `warning`, `error`, `critical`. The alert goes to the channel set for
that system with `/fw alerts`, or to the `default` channel, and is always written to the log.
The same message from the same system is sent at most once per rate-limit window. `send` returns
`True` when a channel message was sent.

## A page in the web dashboard

With the dashboard module on, an extension can add a page with statistics, tables, forms and
buttons, written in Python. The extension cannot send HTML or JavaScript to the browser.

```python
from zdbf.cogs.dashboard.panels import Panel, panels


async def render(ctx):
    return [{"type": "stats", "items": [{"label": "Servers", "value": len(ctx.bot.guilds)}]}]


async def setup(bot):
    panels.register(Panel("my-panel", "My panel", render))
```

The full guide: [dashboard-panels.md](dashboard-panels.md).

## Python packages

If your extension needs packages that ZDBF does not install, import them at the top of the file
as usual. The marketplace scan finds them and offers to install them before loading.

- Wrap optional packages in `try: ... except ImportError:`. The scan treats them as optional and
  does not install them.
- Use the package's import name. When it differs from the pip name (`PIL` → `Pillow`), the bot
  maps common ones for you.
- Do not install packages from your own code at runtime.

## V1 compatibility

V1 extensions run unchanged. These V1 APIs are kept:

- `bot.register_hook`, `bot.unregister_hook`, `bot.emit_hook`, `bot.list_hooks`,
  `bot.get_hook_history`, `bot.disable_hook`, `bot.enable_hook`
- `bot.register_plugin`, `bot.unregister_plugin`, `bot.get_plugin_info`, `bot.get_all_plugins`,
  `bot.check_dependencies`, `bot.detect_conflicts`, `bot.extension_load_times`
- `bot.db.get_guild_prefix`, `bot.db.conn`, `bot.db._get_guild_connection(guild_id)` (per-server
  SQLite files under `data/<guild>/`), `bot.db.increment_command_usage`
- `bot.config.get("prefix")` and the other V1 config keys, `bot.bot_owner_id`
- `from atomic_file_system import global_file_handler`
- The cogs `Task Scheduler`, `Database Migrations` and `Config Validator` by their V1 names
- Embeds still work, but use Components V2 for new code.

## Publishing on the marketplace

Create an account on the [ZSync Marketplace](https://zsync.eu/extension/) and publish your
extension from your account page. Then anyone can install it with `/marketplace install`.

- The installed file name comes from the extension's title: `Weather Alerts` becomes
  `extensions/weather_alerts.py`. Other extensions that depend on yours use that name in
  `__dependencies__`.
- A single `.py` file is the simplest to install and update.
- Set `__version__` and raise it with every release: `/marketplace updates` compares it.
- Expect the safety scan to list risky modules and calls. Explain in your description why you
  need them.
- Keep `async def setup(bot)` at module level so the scan finds the entry point.

## Checklist

- [ ] `async def setup(bot)` that awaits `bot.add_cog`
- [ ] Hybrid commands, grouped, each with a `description`
- [ ] `__version__`, `__author__` and `__description__` set
- [ ] Cog docstring for `/help`
- [ ] Everything started in `cog_load` is stopped in `cog_unload`
- [ ] Settings keys prefixed with the extension name
- [ ] Replies built with `zdbf.ui`, long lists paginated
- [ ] Optional cogs (`Task Scheduler`, `Config Validator`) checked for `None`
- [ ] Works after `/ext reload`
