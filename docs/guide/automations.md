# Automations

Automations make the bot react to things that happen in your server: a member joins, someone
writes a message, a reaction is added, a timer fires. You build them with forms and buttons in
Discord. No code is needed.

Creating and managing automations needs the **Manage Server** permission.

- [Create one](#create-one)
- [Manage them](#manage-them)
- [Templates](#templates)
- [Custom automations](#custom-automations)
- [Conditions](#conditions)
- [Variables](#variables)
- [Cooldowns, history and safety](#cooldowns-history-and-safety)
- [In the web dashboard](#in-the-web-dashboard)

## Create one

1. Run `/hooks create` and pick a template, or `/hooks templates` to read about each first.
2. Fill in the form: channels, roles and messages. Required fields are marked.
3. Optionally add conditions and a cooldown.
4. Save. The automation is active at once.

## Manage them

| Command | Does |
|---|---|
| `/hooks list` | Every automation in this server with its status |
| `/hooks info <automation>` | Details with buttons: enable or disable, edit, conditions, cooldown, history, delete |
| `/hooks toggle <automation>` | Switch it on or off |
| `/hooks history <automation>` | Its recent runs, with errors |
| `/hooks delete <automation>` | Delete it. Panels it posted (role buttons, ticket panel) are removed too. |
| `/hooks conditions` | The condition reference in Discord |
| `/hooks rank [member]` | XP and level (everyone, needs the XP template) |
| `/hooks leaderboard` | Top members by XP (everyone) |

## Templates

### Welcome

Greets new members in a channel.

| Field | Notes |
|---|---|
| Welcome channel | Required |
| Message | Required. Default: `Welcome to **{guild_name}**, {user}. You are member #{member_count}.` |
| Card title, Send as card, Accent colour | Look of the message. Colour as hex, such as `5865F2`. |
| Auto role | Given to every new member |
| Also DM the member, DM text | An optional private welcome |

### Goodbye

Posts a farewell when a member leaves. Fields: channel, message, send as card, accent colour.

### Button roles

Posts a panel with buttons that add or remove roles. The buttons keep working after a restart.

| Field | Notes |
|---|---|
| Panel channel, Roles | Required. Up to 20 roles. |
| Panel title, Panel text, Accent colour | Look of the panel |
| Only one role at a time | Picking a role removes the others from the panel |

The bot's own role must be above the roles it hands out.

### Reaction roles

Gives roles when members react to an existing message.

| Field | Notes |
|---|---|
| Channel of the message, Message ID | Right-click the message and **Copy Message ID** (developer mode) |
| Emoji → role ID | JSON, for example `{"👍": "123456789012345678", "🎮": "234567890123456789"}` |
| Remove role on un-react | On by default |

### Word filter

Acts on messages that contain banned words.

| Field | Notes |
|---|---|
| Banned words | Comma or newline separated |
| Action | `delete`, `delete_warn`, `timeout`, `kick` or `log_only` |
| Timeout seconds | For `timeout`, default 300 |
| Log channel | Where hits are reported |
| Ignored roles | Members with these roles are not checked |
| Whole words only, Case sensitive | Matching options |

### XP and levels

Members earn XP for chatting.

| Field | Notes |
|---|---|
| XP per message | Default 10 |
| Cooldown seconds | XP is given at most once per member in this time, default 60 |
| Level-up channel | Default: the channel the member wrote in |
| Level-up message | Default: `{user} reached level **{level}**.` |
| Role rewards | JSON level → role ID, for example `{"5": "123...", "10": "456..."}` |

`/hooks rank` and `/hooks leaderboard` show the results.

### Recurring announcement

Posts a message every N hours. Fields: channel, message, interval, title, card, colour. For
exact times (every Monday at 9:00) use the [scheduler](scheduler.md) instead.

### Support tickets

Posts a panel with an **Open ticket** button. Each click creates a private channel for the member
and the support role.

| Field | Notes |
|---|---|
| Panel channel, Support role | Required |
| Ticket category | Where ticket channels are created |
| Channel name | Default `ticket-{username}` |
| Panel title, Panel text, Ticket welcome | Texts |
| Save a transcript on close | On by default. Transcripts are kept on the bot under `data/tickets/` (the newest 500 per server) and can be read in the dashboard. |
| Send transcripts to | Optional channel that gets each transcript as a text file |

### Voice activity log

Logs voice joins, leaves, moves and, optionally, mutes to a channel.

### Join-to-create voice

Joining the hub voice channel creates a personal voice channel for the member, which is removed
when it is empty. Fields: hub channel, category, channel name (default `{display_name}'s channel`),
user limit.

### Webhook bridge

Forwards messages, joins or both to an external webhook (Discord, Zapier, Make). The URL must use
`https` and cannot point to a local or private address. You can limit it to some channels and
leave out message content.

## Custom automations

The **Custom** template combines one trigger with up to 15 actions that run in order.

**Triggers**

| Trigger | Options |
|---|---|
| A member joins | |
| A member leaves | |
| A message is sent | Filter: `any`, `contains`, `exact`, `starts_with` or `regex` (case-insensitive), with a keyword or pattern |
| A reaction is added | Optionally only one emoji |
| A member joins a voice channel | Optionally only one channel |
| On a schedule | Every N minutes |

**Actions**

| Action | Does |
|---|---|
| Send a message | Text or a card in a channel |
| Send a DM | To the member who triggered it |
| Add a role, Remove a role | On that member |
| Time out | For a number of seconds |
| Call a webhook | Posts to an `https` address |
| Create a role | With a name |
| Wait | Pause before the next action. All waits together are limited to 10 minutes. |
| Run another automation | Another custom automation, up to 5 levels deep |

Turn on **Stop at the first failed action** if later actions depend on earlier ones.

## Conditions

Conditions decide whether an automation runs. They are a JSON list; by default all rules must
match. Use `{"logic": "or", "rules": [...]}` when any one rule is enough.

```json
[
  {"type": "has_role", "role_id": 123},
  {"type": "lacks_role", "role_id": 456},
  {"type": "channel", "ids": [789]},
  {"type": "time_range", "start": "09:00", "end": "22:00"},
  {"type": "day_of_week", "days": ["mon", "fri"]},
  {"type": "account_age", "min_days": 7},
  {"type": "member_age", "min_days": 1},
  {"type": "chance", "percent": 50},
  {"type": "not_bot"},
  {"type": "role_above", "role_id": 123},
  {"type": "role_below", "role_id": 123},
  {"type": "message_count", "operator": ">=", "value": 50},
  {"type": "variable", "name": "content", "operator": "contains", "value": "help"}
]
```

| Type | Matches when |
|---|---|
| `has_role`, `lacks_role` | The member has, or does not have, the role |
| `role_above`, `role_below` | The member's highest role is above or below the role |
| `channel`, `not_channel` | The event happened in, or outside, these channel IDs |
| `time_range` | The time is between `start` and `end` (`HH:MM`) |
| `day_of_week` | Today is one of `mon` `tue` `wed` `thu` `fri` `sat` `sun` |
| `account_age`, `member_age` | The Discord account, or the membership, is at least `min_days` old |
| `chance` | A random roll succeeds, `percent` from 0 to 100 |
| `not_bot` | The member is not a bot |
| `content_contains` | The message contains a text |
| `message_count` | The member's message count in this server compares to `value`. Counting starts when the first automation with this rule is created. |
| `variable` | Any [variable](#variables) compares to `value` |

Operators: `==`, `!=`, `contains`, `startswith`, `>`, `<`, `>=`, `<=`.

## Variables

Use these in any message, title or name:

| Variable | Value |
|---|---|
| `{user}` | Mention of the member |
| `{username}`, `{display_name}`, `{user_id}` | Their name, server name and ID |
| `{server}` (or `{guild_name}`), `{member_count}` | The server and its member count |
| `{channel}`, `{channel_name}` | Channel mention and name |
| `{content}` | The message text (message triggers) |
| `{emoji}` | The reaction (reaction triggers) |
| `{voice_channel}` | The voice channel (voice triggers) |
| `{date}`, `{time}`, `{timestamp}` | The current date and time |
| `{level}` | The new level (XP level-up message) |
| `{random:1-100}` | A random number in the range |
| `{math:2*(3+4)}` | The result of a calculation |

## Cooldowns, history and safety

- **Cooldown.** In `/hooks info`, press **Cooldown** and set seconds and whether it applies per
  member (`user`) or to the whole server (`server`).
- **History.** Every run is recorded with its result: `/hooks history`.
- **Automatic switch-off.** An automation that fails 10 times in a row is disabled and an alert is
  sent to the `automations` alert channel (`/fw alerts`). Fix the cause, then enable it again.
- **Permissions.** The bot needs the Discord permissions for what an automation does: Manage Roles
  for roles (and its role above them), Moderate Members for timeouts, Manage Channels for tickets
  and voice channels.

## In the web dashboard

The **Automations** page of the [dashboard](dashboard.md) shows the same automations with the same
forms, an editor for the action list of custom automations, conditions, run history, and on, off
and delete. The **Tickets** page lists open tickets and the saved transcripts.
