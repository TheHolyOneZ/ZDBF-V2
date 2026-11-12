# Event hooks

The hook bus lets extensions react to things the framework does (a command ran, an extension
loaded, a scheduled task fired) and lets extensions talk to each other with their own events.
Hooks run in a background worker, one failing hook never blocks the others, and a hook that keeps
failing is paused by a circuit breaker.

For Discord events (messages, reactions, members), use normal discord.py listeners
(`@commands.Cog.listener()`). Hooks are for framework and extension events.

- [Listening](#listening)
- [Built-in events](#built-in-events)
- [Your own events](#your-own-events)
- [How hooks run](#how-hooks-run)
- [Circuit breaker](#circuit-breaker)
- [Managing hooks from Discord](#managing-hooks-from-discord)
- [Hooks and scheduled tasks](#hooks-and-scheduled-tasks)
- [API reference](#api-reference)

## Listening

```python
class Audit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.register_hook("command_executed", self.on_command_used, priority=5)

    async def on_command_used(self, bot, command_name, author, guild, **kwargs):
        if guild is not None:
            await bot.db.execute(
                "INSERT INTO audit_log (guild_id, user_id, command) VALUES (?, ?, ?)",
                (guild.id, author.id, command_name))
```

- The callback must be `async`. It is called with `bot=` and the event's payload as keyword
  arguments.
- **Always accept `**kwargs`.** Events may get more fields in later versions.
- `priority`: higher runs first (default `0`).
- Registering the same callback twice for an event has no effect.
- Hooks registered from your extension's module are removed automatically when it unloads or
  reloads, so you do not need to unregister them in `cog_unload`.

## Built-in events

| Event | Payload | When |
|---|---|---|
| `bot_ready` | `bot_user` | The first time the bot is ready (not on reconnects) |
| `guild_joined` | `guild` | The bot joined a server |
| `guild_left` | `guild` | The bot left or was removed from a server |
| `command_executed` | `command_name`, `author`, `guild`, `ctx` | A command started (prefix or slash). `guild` is `None` in DMs. |
| `command_error` | `command_name`, `error`, `author`, `guild` | A command raised an error |
| `extension_loaded` | `extension_name` | An extension or module loaded (also after a reload) |
| `extension_unloaded` | `extension_name` | An extension or module was unloaded |
| `extension_reloaded` | `extension_name` | An extension was reloaded |
| `scheduled_task` | `task_id`, `task_name`, `ok` | A scheduler task finished, with `ok=False` if it failed |
| `cluster_broadcast` | `source`, `message`, `data` | Another cluster sent `/cluster broadcast` |

`extension_name` is the full module name, such as `extensions.shop` or `zdbf.cogs.backup`.
`command_name` is the qualified name, such as `backup create`.

## Your own events

Emit an event and let other extensions listen:

```python
count = await self.bot.emit_hook("economy_transaction", user=user, amount=50, guild=guild)
```

`emit_hook` queues the event and returns at once with the number of hooks registered for it. List
the events you emit in `__provides_hooks__` and the ones you listen to in `__listens_to_hooks__`
so `/plugins` can show how extensions connect.

Use a prefix that names your extension (`economy_transaction`, not `transaction`) and keep payloads
to plain values and Discord objects.

## How hooks run

1. `emit` puts the event in a queue (up to 1,000 events) and returns.
2. A background worker takes events in order and calls each registered hook, highest priority first.
3. Every hook has **10 seconds**. A hook that takes longer is cancelled and counted as a failure.
4. An exception in a hook is logged with its traceback and counted; the other hooks still run.
5. The run is added to the history (`/eventhooks history`) with the number of successes and
   failures, the queue delay and the average time.

If the queue is full, the event is dropped and an alert goes to the `eventhooks` alert channel.
A hook that needs to do slow work should start a task (`asyncio.create_task`) and return.

`await bot.hooks.emit_now(event, **payload)` runs the hooks right away, in the caller's task, and
returns the history entry. Use it in tests, or when you must know that every hook finished.

## Circuit breaker

A hook that fails **5 times within 5 minutes** is paused for **60 seconds** and an alert is sent.
After the pause it runs again; a hook that keeps failing is paused again. `/eventhooks reset
<hook_id>` closes the breaker at once, `/eventhooks enable <hook_id>` does too.

## Managing hooks from Discord

All bot owner only:

| Command | Does |
|---|---|
| `/eventhooks list` | Every registered hook with executions, failures and average time |
| `/eventhooks history [event]` | Recent runs |
| `/eventhooks disable <hook_id>` | Stop a hook from running. Kept across restarts. |
| `/eventhooks enable <hook_id>` | Run it again (also closes its breaker) |
| `/eventhooks reset <hook_id>` | Close its circuit breaker |
| `/eventhooks alerts [channel]` | Where hook alerts go |

A hook ID has the form `event:module.QualifiedName`, for example
`command_executed:extensions.audit.Audit.on_command_used`. The **System** page of the web dashboard
lists hooks and can turn them on and off as well.

## Hooks and scheduled tasks

A scheduler task of type `hook` emits the event named in its `hook_name` with the task's `data`
plus `_task_name` and `_task_id`:

```python
async def cog_load(self):
    self.bot.register_hook("weekly_report", self.weekly_report)

async def weekly_report(self, bot, guild_id=None, _task_name=None, _task_id=None, **kwargs):
    guild = bot.get_guild(guild_id) if guild_id else None
    ...
```

Create such tasks with `/schedule create ... task_type:hook hook_name:weekly_report`, or from code
as shown in [extensions.md](extensions.md#scheduled-tasks).

## API reference

On the bot (V1 compatible):

| Call | Does |
|---|---|
| `bot.register_hook(event, callback, priority=0)` | Register; returns `False` if the callback is not async |
| `bot.unregister_hook(event, callback)` | Remove one registration |
| `await bot.emit_hook(event, **payload)` | Queue an event; returns the number of receivers |
| `bot.list_hooks()` | `{event: [callback names]}` |
| `bot.get_hook_history(limit=20)` | Recent runs as dicts |
| `bot.disable_hook(hook_id)`, `bot.enable_hook(hook_id)` | Same as the commands |

On `bot.hooks` (`HookBus`):

| Call | Does |
|---|---|
| `register`, `unregister`, `emit` | As above |
| `await emit_now(event, **payload)` | Run the hooks now and return the result |
| `unregister_module(module)` | Remove every hook whose callback lives in that module |
| `find(hook_id)`, `all_hooks()` | Look up registrations |
| `history`, `metrics`, `breaker` | Recent runs, counters, the circuit breaker |
