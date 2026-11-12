# Scheduler

Run tasks at fixed times with cron expressions: post a message every Monday at 9:00, fire an
event for an extension every hour, write a log line at midnight. The scheduler commands need the
**Manage Server** permission.

- [Create a task](#create-a-task)
- [Cron expressions](#cron-expressions)
- [Manage tasks](#manage-tasks)
- [Time zone and limits](#time-zone-and-limits)

## Create a task

```
/schedule create name:weekly-reminder cron:0 9 * * mon task_type:message channel:#general message:Weekly meeting in one hour.
```

| Option | Meaning |
|---|---|
| `name` | A name for the task |
| `cron` | When it runs, see below |
| `task_type` | `message` (default), `hook` or `log` |
| `channel` | Where a message task posts. Default: the current channel. |
| `message` | The text of a message task, or of the log line of a log task |
| `hook_name` | The event a hook task fires (for extensions), default `scheduled_task` |
| `max_runs` | Switch the task off after this many runs |

| Type | Does |
|---|---|
| `message` | Posts the message in the channel |
| `hook` | Fires an event that extensions can listen to (see [event hooks](../dev/hooks-and-events.md)) |
| `log` | Writes a line to the bot log |

Tasks are kept in the database and continue after a restart.

## Cron expressions

Five fields, separated by spaces:

```
┌──────── minute        0-59
│ ┌────── hour          0-23
│ │ ┌──── day of month  1-31
│ │ │ ┌── month         1-12 or jan-dec
│ │ │ │ ┌ day of week   0-6 or sun-sat (0 = Sunday)
│ │ │ │ │
0 9 * * mon-fri
```

| Expression | Runs |
|---|---|
| `0 9 * * mon-fri` | 9:00 on weekdays |
| `30 18 * * fri` | 18:30 every Friday |
| `*/15 * * * *` | Every 15 minutes |
| `0 */6 * * *` | Every 6 hours |
| `0 0 1 * *` | Midnight on the first of every month |
| `0 12 * * 0` | Noon every Sunday |

Each field takes `*`, a number, a list (`1,15`), a range (`9-17`) and a step (`*/5`, `9-17/2`).

Macros: `@hourly`, `@daily` (also `@midnight`), `@weekly`, `@monthly`, `@yearly` (also `@annually`).

`/schedule preview <cron>` explains an expression in plain words and lists its next runs. Use it
before creating a task.

## Manage tasks

| Command | Does |
|---|---|
| `/schedule list` | Tasks in this server |
| `/schedule info <task>` | Details with buttons: enable, disable, run now, delete |
| `/schedule toggle <task>` | Switch a task on or off |
| `/schedule delete <task>` | Delete it |
| `/schedule alerts [channel]` | Where failed runs are reported |

The **Automations** page of the [web dashboard](dashboard.md) has a **Scheduled tasks** tab with a
live explanation of the expression, run now, pause and delete.

## Time zone and limits

Set by the bot host in `config.toml`:

| Key | Default | Meaning |
|---|---|---|
| `[scheduler] timezone` | `UTC` | The time zone cron times use. Any IANA name, such as `Europe/Berlin` or `America/New_York`. |
| `[scheduler] max_tasks_per_guild` | `25` | Tasks per server |

Daylight saving time is handled by the time zone: `0 9 * * *` in `Europe/Berlin` runs at 9:00
local time all year.

Upgrading from V1? V1 counted `0` as Monday. V2 follows standard cron (`0` = Sunday), and tasks
migrated from V1 are converted for you.
