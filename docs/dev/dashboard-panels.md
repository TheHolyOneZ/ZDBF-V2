# Dashboard panels for extensions

An extension can give itself a page in the [ZDBF Dashboard](../guide/dashboard.md): statistics,
tables, lists, text, forms and buttons, written entirely in Python. The page appears under
**Panels** as soon as the extension loads and disappears when it unloads.

A panel is **data, not code**. The extension returns a list of blocks; the bot cleans them and the
dashboard draws them with its own components. An extension can never send HTML, JavaScript or PHP
to the website, so a panel cannot run code in an admin's browser.

- [A first panel](#a-first-panel)
- [How it works](#how-it-works)
- [`Panel`](#panel)
- [The context](#the-context)
- [Blocks](#blocks)
- [Forms and buttons](#forms-and-buttons)
- [Capabilities, roles and approval](#capabilities-roles-and-approval)
- [Lifecycle](#lifecycle)
- [Limits](#limits)
- [Errors](#errors)
- [A complete example](#a-complete-example)
- [Trying it locally](#trying-it-locally)

## A first panel

```python
from zdbf.cogs.dashboard.panels import Panel, panels


async def render(ctx):
    bot = ctx.bot
    return [
        {"type": "stats", "title": "Right now", "items": [
            {"label": "Servers", "value": len(bot.guilds)},
            {"label": "Latency (ms)", "value": round(bot.latency * 1000)},
        ]},
        {"type": "table", "title": "Biggest servers", "columns": ["Server", "Members"],
         "rows": [[g.name, g.member_count] for g in sorted(bot.guilds, key=lambda g: -(g.member_count or 0))[:10]]},
    ]


async def setup(bot):
    panels.register(Panel("server-sizes", "Server sizes", render, description="Member counts per server"))
```

Save it as `extensions/server_sizes.py`, load it with `/ext load server_sizes`, and open
**Panels → Server sizes** in the dashboard.

Panels need the `dashboard` module to be shown. Registering one while the module is off is
harmless; it shows up once the module is on.

## How it works

```
extension                     bot (Dashboard module)                  website                browser
─────────                     ──────────────────────                  ───────                ───────
panels.register(Panel)  ──>   adds actions "panel.<id>" and
                              "panel.<id>.<action>" to the
                              action registry
                              lists the panel in the "meta"   ──push──>  stores meta  ──live──>  Panels menu
                              state with every action's
                              capability
                                                                         <──── api/command.php "panel.<id>"
                                                                         checks the user's role
                                                                         against the capability, queues it
                              pulls the command  <──pull────
                              checks capability, lock, approval
                              calls render(ctx), cleans blocks
                              posts the result  ──push──────────────>  result  ──────────>  draws blocks
```

The same path is used for every dashboard action, so a panel gets the same protection as the
built-in pages: the website checks the user's role, the bot checks its own capability list, the
approval rules and the lock, and records the action in its audit log.

## `Panel`

```python
Panel(
    id="my-panel",                 # 2-40 characters: a-z, 0-9, - and _; starts with a letter or digit
    title="My panel",              # shown in the menu and the command palette
    render=render,                 # async def render(ctx) -> list[dict]
    description="What it shows",   # shown above the panel (default: "From <module>")
    capability="view",             # needed to see the panel
    actions={"save": save},        # name -> async def handler(ctx); same naming rules as id
    action_capability="extensions",# needed to run any of the actions
)
```

`panels.register(panel)` validates the IDs and capability names and raises `PanelError` if one is
wrong. Registering an ID that already exists replaces the old panel.

Other calls:

| Call | Does |
|---|---|
| `panels.unregister("my-panel")` | Removes a panel. Returns `False` if it did not exist. |
| `panels.unregister_module("extensions.mine")` | Removes every panel registered from a module (done for you on unload) |
| `panels.describe()` | The list the dashboard receives |

## The context

`render` and every action handler receive an `ActionContext`:

| Attribute or method | Value |
|---|---|
| `ctx.bot` | The bot |
| `ctx.args` | The values sent with the action: the form fields, or `{}` for a button and for `render` |
| `ctx.user` | The dashboard user: `{"id": "...", "name": "...", "role": "..."}`. This is a website account, not a Discord user. |
| `ctx.command_id` | Unique ID of this request |
| `ctx.text(name, default=None, max_length=2000)` | A string argument; raises `ActionError` if missing or too long |
| `ctx.integer(name, default=None, minimum=None, maximum=None)` | An integer argument (digit strings are converted); raises `ActionError` if missing or out of range |
| `ctx.flag(name, default=False)` | A boolean argument |
| `await ctx.progress("Step 2 of 3")` | Shows a progress note in the browser while a long action runs |

## Blocks

`render` returns a list of blocks. Each block is a dict with a `type` and an optional `title`
(shown as the card heading). Blocks are drawn as cards in the order you return them.

### `stats`

A row of figures.

```python
{"type": "stats", "title": "Today", "items": [
    {"label": "Orders", "value": 42},
    {"label": "Revenue", "value": 1234.5, "hint": "In coins, before refunds"},
]}
```

`value` may be a number, text, `True`/`False` (shown as yes/no) or `None` (shown as `-`). Numbers
are formatted with thousands separators. `hint` is shown on hover.

### `table`

```python
{"type": "table", "title": "Top members", "columns": ["Member", "XP", "Active"],
 "rows": [["Alice", 1520, True], ["Bob", 980, False]]}
```

Each row is a list with one value per column; extra values are dropped. Wide tables scroll
sideways on small screens.

### `text`

```python
{"type": "text", "title": "About", "text": "Plain text. Line breaks are kept."}
```

Shown as plain text: no Markdown, no HTML.

### `list`

```python
{"type": "list", "title": "Recent events", "items": ["Alice bought a sword", "Bob sold a shield"]}
```

### `form`

```python
{"type": "form", "title": "Settings", "action": "save", "submit": "Save settings", "fields": [
    {"key": "name", "label": "Shop name", "kind": "text", "value": "The Shop", "required": True},
    {"key": "note", "label": "Welcome note", "kind": "textarea", "value": ""},
    {"key": "tax", "label": "Tax (%)", "kind": "number", "value": 5},
    {"key": "open", "label": "Shop is open", "kind": "bool", "value": True},
    {"key": "currency", "label": "Currency", "kind": "choice", "value": "coins",
     "choices": ["coins", "gems", "tokens"]},
]}
```

| Field key | Meaning |
|---|---|
| `key` | The name in `ctx.args` |
| `label` | The visible label |
| `kind` | `text`, `textarea`, `number`, `bool` or `choice` (default `text`) |
| `value` | The current value, filled in |
| `choices` | The options of a `choice` field |
| `required` | The browser refuses to submit an empty `text`, `textarea` or `number` field |

`action` names the handler in `Panel(actions=...)` that receives the form. Without an `action` the
submit button is disabled. `submit` is the button text (default `Save`).

### `buttons`

```python
{"type": "buttons", "title": "Actions", "buttons": [
    {"action": "restock", "label": "Restock", "style": "primary"},
    {"action": "reset", "label": "Reset all", "style": "danger",
     "confirm": "This removes every order. Continue?"},
]}
```

`style` is `primary`, `secondary` (default) or `danger`. With `confirm`, the browser asks first.

Unknown block types and unknown field kinds are left out without an error, so a panel written for
a newer version still shows what it can.

## Forms and buttons

A form submit or a button click calls the named handler with the values in `ctx.args`:

| Field kind | Arrives as |
|---|---|
| `text`, `textarea`, `choice` | `str` |
| `number` | `int` or `float`, or `None` when empty |
| `bool` | `bool` |

**Never trust these values.** They come from a browser. Check them as you would any user input:

```python
async def save(ctx):
    name = ctx.text("name", max_length=60).strip()
    tax = ctx.args.get("tax")
    if not isinstance(tax, int | float) or not 0 <= tax <= 50:
        raise ActionError("Tax must be between 0 and 50.")
    await ctx.bot.db.kv_set("shop.settings", {"name": name, "tax": tax})
    return f"Saved by {ctx.user.get('name')}."
```

A handler returns a message for the toast in the browser: a string, `{"message": "..."}`, or
`None` for no message. After every action the panel is rendered again, so the page always shows
the new state. You do not return blocks from a handler.

The panel does not refresh on its own. It is drawn when the page opens and after each action. Add
a **Refresh** button with a handler that returns `None` if people want a fresh view.

## Capabilities, roles and approval

Two capabilities control a panel:

| Setting | Default | Controls |
|---|---|---|
| `capability` | `view` | Seeing the panel |
| `action_capability` | `extensions` | Every form and button of the panel |

They are the same capabilities as the rest of the dashboard: `view`, `logs`, `chat.read`,
`chat.send`, `chat.moderate`, `commands.run`, `commands.owner`, `extensions`, `files.read`,
`files.write`, `automations`, `scheduler`, `settings`, `backups`, `backups.restore`, `presence`,
`database`, `config`, `marketplace`, `guilds.leave`, `system`.

Pick the one that matches what the action really does:

- Changing your extension's settings: `settings`.
- Moderation or messages: `chat.send` or `chat.moderate`.
- Anything as dangerous as shutting down or deleting data: `system` or `config`.

Then three checks apply, in order:

1. **The website role.** Every user who can open **Panels** sees the list, but opening a panel or
   running an action without the capability answers "Your role does not allow this". Viewers have `view`; Operators also have
   `extensions` and `settings`; see [the roles](../guide/dashboard.md#users-roles-and-logins).
2. **The bot's capability list.** If the bot owner removed the capability from
   `[dashboard] capabilities`, or locked the dashboard, the action is refused.
3. **Approval.** If the capability is in `[dashboard] approval`, the bot owner gets a DM with
   **Approve** and **Deny** before the handler runs. The DM shows the panel title and action name.

`render` is never held for approval by default, because `view` is not in the approval list.

Every action that is not `view` is written to the bot's audit log (`/dashboard audit`) with the
dashboard user and the outcome.

## Lifecycle

| Event | What happens |
|---|---|
| Your `setup` (or `cog_load`) calls `panels.register` | The panel and its actions exist. The dashboard lists it with the next state push: at once if someone has the dashboard open, otherwise within `[dashboard] idle_interval` seconds. |
| `/ext reload` or a hot reload | `setup` runs again and registers the same IDs, which replace the old ones |
| `/ext unload`, or the extension is removed | Every panel registered from the extension's module is removed |
| The dashboard module is turned off and on again | The panel registry starts empty. Reload your extension to register its panels again. |

Panels are matched to an extension by the module of their `render` function. If you rename a
panel ID, the old one stays until the extension is unloaded; call `panels.unregister("old-id")`
or unload and load the extension.

## Limits

The bot trims blocks before they leave it:

| What | Limit |
|---|---|
| Blocks per panel | 30 |
| Block title | 120 characters |
| Stats items | 12 per block; label 60, hint 120 characters |
| Table | 12 columns (60 characters each), 500 rows, 300 characters per cell |
| Text | 4,000 characters |
| List | 100 items, 300 characters each |
| Form | 20 fields; key 40, label 80 characters; 50 choices of 80 characters |
| Buttons | 10 per block; label 40, confirm text 200 characters |
| Action message | 500 characters |
| `render` time | 30 seconds |
| Action time | 60 seconds |

Keep `render` fast: it runs every time someone opens the panel and after every action. Cache
expensive data in your extension and show it from the cache.

## Errors

| In your code | The user sees |
|---|---|
| `raise ActionError("Tax must be between 0 and 50.")` | That message |
| `render` returns something that is not a list | "The panel returned something the dashboard cannot show." |
| Any other exception | "The action failed: `ValueError`. See the bot log." The traceback is in the bot log. |
| Too slow | "The action took too long and was stopped." |

Import `ActionError` with `from zdbf.cogs.dashboard.actions import ActionError`.

## A complete example

A small shop with settings, statistics and a reset button. Settings are stored in the database
so they survive restarts.

```python
from discord.ext import commands

from zdbf.cogs.dashboard.actions import ActionError
from zdbf.cogs.dashboard.panels import Panel, panels
from zdbf.ui import cards

__version__ = "1.0.0"
__description__ = "A tiny shop with a dashboard panel"

KEY = "shop.settings"
DEFAULTS = {"name": "The Shop", "tax": 5, "open": True, "orders": 0}


async def load(bot):
    return {**DEFAULTS, **(await bot.db.kv_get(KEY, {}) or {})}


async def render(ctx):
    s = await load(ctx.bot)
    return [
        {"type": "stats", "title": "Shop", "items": [
            {"label": "Orders", "value": s["orders"]},
            {"label": "Tax (%)", "value": s["tax"]},
            {"label": "Open", "value": s["open"]},
        ]},
        {"type": "form", "title": "Settings", "action": "save", "fields": [
            {"key": "name", "label": "Shop name", "kind": "text", "value": s["name"], "required": True},
            {"key": "tax", "label": "Tax (%)", "kind": "number", "value": s["tax"]},
            {"key": "open", "label": "Shop is open", "kind": "bool", "value": s["open"]},
        ]},
        {"type": "buttons", "buttons": [
            {"action": "refresh", "label": "Refresh"},
            {"action": "reset", "label": "Reset orders", "style": "danger",
             "confirm": "Set the order count back to 0?"},
        ]},
    ]


async def save(ctx):
    s = await load(ctx.bot)
    tax = ctx.args.get("tax")
    if not isinstance(tax, int | float) or not 0 <= tax <= 50:
        raise ActionError("Tax must be between 0 and 50.")
    s.update(name=ctx.text("name", max_length=60).strip() or DEFAULTS["name"], tax=tax, open=ctx.flag("open"))
    await ctx.bot.db.kv_set(KEY, s)
    return "Saved."


async def refresh(ctx):
    return None


async def reset(ctx):
    s = await load(ctx.bot)
    s["orders"] = 0
    await ctx.bot.db.kv_set(KEY, s)
    return "Orders reset."


class Shop(commands.Cog, name="Shop"):
    """A tiny shop."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(description="Place an order")
    async def order(self, ctx):
        s = await load(self.bot)
        if not s["open"]:
            await ctx.send(view=cards.warning("Closed", f"{s['name']} is closed right now."))
            return
        s["orders"] += 1
        await self.bot.db.kv_set(KEY, s)
        await ctx.send(view=cards.success("Order placed", f"Thanks for shopping at {s['name']}."))


async def setup(bot):
    await bot.add_cog(Shop(bot))
    panels.register(Panel(
        "shop", "Shop", render, description="Orders and settings of the shop extension",
        actions={"save": save, "refresh": refresh, "reset": reset},
        action_capability="settings"))
```

## Trying it locally

You do not need a web host to build a panel:

1. Run the dashboard on your machine with PHP's built-in server, as described in
   [dashboard-internals.md](dashboard-internals.md#running-it-locally).
2. Enable the module (`[modules] dashboard = true`), run `/dashboard export` for the setup key,
   open `http://127.0.0.1:8090/setup.php` and pair with the shown command. Plain HTTP is allowed
   for `127.0.0.1` and `localhost`.
3. Edit your extension: hot reload re-registers the panel, then reopen it in the browser.

For a quick check without a browser, call the cleaner directly:

```python
from zdbf.cogs.dashboard.panels import clean_blocks

print(clean_blocks(await render(ctx)))     # exactly what the browser would receive
```
