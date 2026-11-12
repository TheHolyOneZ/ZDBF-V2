# UI kit (`zdbf.ui`)

Every message ZDBF sends is a [Components V2](https://discord.com/developers/docs/components/overview)
layout: containers, text, separators, sections, buttons and selects, no embeds. `zdbf.ui` wraps
discord.py's `LayoutView` so that building one takes a line or two, and handles what usually goes
wrong: messages over Discord's limits, menus clicked by the wrong person, expired buttons and
errors inside callbacks.

```python
from zdbf.ui import BaseView, FormField, FormModal, ListDetailView, Paginator, SelectPager
from zdbf.ui import button, cards, confirm, link_button, respond, row, select
```

- [Status cards](#status-cards)
- [Building a card](#building-a-card)
- [Text helpers](#text-helpers)
- [Interactive views](#interactive-views)
- [Buttons, selects and rows](#buttons-selects-and-rows)
- [Pagination](#pagination)
- [List and detail pages](#list-and-detail-pages)
- [Confirmations](#confirmations)
- [Modals](#modals)
- [Sending](#sending)
- [Limits](#limits)
- [Style rules](#style-rules)

## Status cards

The quickest answer: a card with a coloured edge, a title and a message.

```python
await ctx.send(view=cards.success("Saved", "Your settings were stored."))
await ctx.send(view=cards.info("Heads up", "The shop opens at 9:00."))
await ctx.send(view=cards.warning("Low stock", "Only 2 swords left."))
await ctx.send(view=cards.error("Not found", "There is no item called `axe`."))
```

Each takes the same keyword arguments as `cards.card` (below), such as `foot=` or `thumbnail=`.

## Building a card

```python
box = cards.card(
    "Profile",                                   # title, None for none
    cards.kv({"Level": 5, "XP": "1,250"}),       # body: strings and components, in order
    cards.sep(),
    "Some more text",
    subtitle="Member since 2024",
    accent="gold",
    thumbnail=ctx.author.display_avatar.url,
    foot="Updated just now",
)
await ctx.send(view=cards.static(box))
```

| Argument | Meaning |
|---|---|
| `title` | Heading of the card |
| `*body` | Strings (become text blocks) and components (separators, sections, rows...) |
| `subtitle` | Small line under the title |
| `emoji` | Shown before the title only when the bot owner enabled `[ui] decorative_emoji` |
| `accent` | Edge colour: `primary` (default), `brand`, `info`, `success`, `warning`, `error`/`danger`, `gold`, `muted`, a `discord.Colour`, an `int`, or `None` |
| `thumbnail` | An image URL on the right of the title |
| `foot` | Small footer text |

`cards.static(*items)` turns cards into a view that never times out. If the content is too large
for one message, it becomes a paginated view on its own.

Building blocks for custom layouts:

| Function | Returns |
|---|---|
| `cards.container(*children, accent=...)` | A container without the title logic |
| `cards.text(content)` | A text block (truncated to the limit) |
| `cards.sep(large=False, visible=True)` | A separator; `visible=False` for spacing only |
| `cards.section(content, accessory)` | Up to three text blocks with a button or thumbnail on the right |
| `cards.header(title, subtitle=None, emoji=None, level=2)` | The Markdown of a heading |
| `cards.footer(content, with_time=False)` | A small footer line |

## Text helpers

| Function | Gives |
|---|---|
| `cards.kv({"Key": "value"}, code=False)` | `**Key**  value` lines; `code=True` puts values in backticks |
| `cards.fields({"Title": "text"})` | Bold titles with their text below, separated by blank lines |
| `cards.bar(value, maximum=100, width=14)` | A progress bar such as `▰▰▰▰▱▱▱  57%` |
| `cards.timestamp(when=None, style="R")` | A Discord timestamp (`<t:...:R>`) from a datetime, a Unix time or an ISO string |
| `cards.codeblock(content, lang="")` | A safe code block (inner backticks are escaped) |
| `cards.truncate(value, limit=4000)` | Shortens text with `…` |
| `status_dot(ok)` | 🟢 for `True`, 🔴 for `False`, 🟡 for `None` |

## Interactive views

Subclass `BaseView`, draw everything in `build()`, and call `refresh()` after a change:

```python
import discord

from zdbf.ui import BaseView, button, cards, row


class Counter(BaseView):
    def __init__(self, author_id: int):
        super().__init__(author_id=author_id, timeout=300)
        self.n = 0

    def build(self):
        self.clear_items()
        box = cards.card("Counter", f"Clicked **{self.n}** times")

        async def plus(interaction: discord.Interaction):
            self.n += 1
            await self.refresh(interaction)

        async def reset(interaction: discord.Interaction):
            self.n = 0
            await self.refresh(interaction)

        box.add_item(row(button("+1", plus, style=discord.ButtonStyle.primary), button("Reset", reset)))
        self.add_item(box)


await Counter(ctx.author.id).send(ctx)
```

What `BaseView` does for you:

- **Only its owner can click.** `author_id` (taken from the command's author by default) and bot
  owners may use it; anyone else gets a private "Not your menu" card. Pass `author_id=None` after
  `send` to let everyone use it.
- **Times out cleanly.** After `timeout` seconds (default 300, `None` for never) every button and
  select is disabled and the message updated. Link buttons stay active.
- **Errors are caught.** An exception in a callback is logged and the user sees a private error
  card instead of "This interaction failed".
- **`refresh(interaction)`** rebuilds the view and edits the message, whether the interaction was
  already answered or not.
- **`send(target)`** works with a command context or an interaction and remembers the message.

For buttons that must keep working after a restart (role panels, ticket buttons), use
discord.py's `DynamicItem` with a `custom_id` template and register it once with
`bot.add_dynamic_items(MyButton)`, as `zdbf/cogs/automations/persistent.py` does. Put everything
the button needs to know into its `custom_id`.

## Buttons, selects and rows

```python
button("Save", on_save, style=discord.ButtonStyle.success, emoji=None, disabled=False, custom_id=None)
link_button("Docs", "https://example.com")
select(options, on_pick, placeholder="Pick one", min_values=1, max_values=1)
row(button_a, button_b, None)          # None items are skipped
```

Callbacks are `async def callback(interaction)`. For `select`, read the values from the select
object or use `SelectPager` below. `select` takes at most 25 options; an empty list shows a
disabled placeholder.

## Pagination

Anything that can grow past one message must be paginated.

```python
await Paginator.from_lines(lines, per_page=10, title="Leaderboard").send(ctx)
await Paginator.from_text(long_text, title="Changelog").send(ctx)
await Paginator(["Page one", "Page two"], title="Guide", foot="Use the arrows").send(ctx)
```

| Argument | Meaning |
|---|---|
| `pages` | A list of strings, or lists of components |
| `title`, `subtitle`, `accent`, `foot`, `thumbnail`, `emoji` | As in `cards.card` |
| `start` | The first page shown |
| `links` | Link buttons shown on every page |
| `author_id`, `timeout` | As in `BaseView` |

`from_lines` also splits a page early when it would pass 3,000 characters. Subclass `Paginator`
and override `extra_items()` to add your own buttons under the navigation.

`chunk_lines(lines, per_page)` and `chunk_text(text)` split text without a view.
`nav_row(index, count, goto)` gives the « ‹ › » row for your own paged views.

**More than 25 options in a select:** `SelectPager` pages them.

```python
self.picker = SelectPager(options, self.on_pick, placeholder="Choose a member")

def build(self):
    ...
    for r in self.picker.rows(self):
        box.add_item(r)
```

## List and detail pages

`ListDetailView` is the pattern most framework menus use: a paged list with a select to open an
item, a detail card with its own buttons, and a Back button.

```python
class ItemList(ListDetailView[dict]):
    title = "Shop items"
    per_page = 8

    def item_key(self, item):
        return str(item["id"])

    def item_line(self, item):
        return f"**{item['name']}**  {item['price']} coins"

    def detail(self, item):
        return cards.card(item["name"], cards.kv({"Price": item["price"], "Stock": item["stock"]}))

    def detail_controls(self, item):
        async def delete(interaction):
            ...
            self.replace_items(await load_items())
            self.selected = None
            await self.refresh(interaction)
        return [button("Delete", delete, style=discord.ButtonStyle.danger)]


await ItemList(items, author_id=ctx.author.id).send(ctx)
```

Override `subtitle()`, `intro()`, `list_controls()` and `foot()` for more. Set `self.note` to show
a one-off message under the card.

## Confirmations

```python
view = await confirm(ctx, "Delete everything?", "This cannot be undone.",
                     confirm_label="Delete", danger=True, timeout=60)
if view.value:          # True confirmed, False cancelled, None timed out
    ...
```

`confirm` sends the question, waits for the answer and returns the view. `view.interaction` is the
button press, if you want to answer it.

## Modals

```python
async def done(interaction, values):
    await interaction.response.send_message(view=cards.success("Saved", values["name"]), ephemeral=True)

modal = FormModal("Rename item", [
    FormField("name", "New name", placeholder="Sword of Light", max_length=60),
    FormField("notes", "Notes", paragraph=True, required=False),
], done)
await interaction.response.send_modal(modal)
```

`FormField(key, label, description=None, placeholder=None, default=None, required=True,
paragraph=False, min_length=None, max_length=None)`. A modal holds up to five fields; values
arrive stripped of surrounding spaces. Modals can only be opened from an interaction (a button,
a select or a slash command), not from a prefix command.

## Sending

`await respond(target, view, ephemeral=False, files=None)` sends a view to a context or an
interaction, answering or following up as needed. `ephemeral` is ignored for prefix commands.
Every send through the kit pings users but never `@everyone` or roles.

## Limits

Discord rejects a layout with more than 4,000 characters of text or 40 components. The kit
truncates single text blocks, and `cards.static` turns content that is too large into pages.
`cards.fits(view)` tells you whether a view you built yourself fits.

## Style rules

The framework's output is restrained on purpose:

- Status dots (🟢🟡🔴⚪) are the only emoji in framework messages. Pass other emoji as `emoji=`
  so the bot owner can turn them on with `[ui] decorative_emoji`. `tests/test_ui_limits.py`
  checks the framework's own code for this.
- Use accents for meaning: `success`, `warning`, `error`, `info`; `primary` for neutral cards.
- One card per message is the norm; use sections and separators instead of several cards.
- Put actions on buttons under the card, not in text ("type `!confirm`").
