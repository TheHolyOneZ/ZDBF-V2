# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import inspect
import types
import typing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands, ui
from discord.ext import commands

from .. import __version__
from ..core.permissions import access_level
from ..ui import BaseView, FormField, FormModal, Glyph, button, cards, link_button, nav_row, row
from ..utils import plural

if TYPE_CHECKING:
    from ..core.bot import ZDBFBot

REPO_URL = "https://github.com/TheHolyOneZ/ZDBF-V2"
MARKETPLACE_URL = "https://zsync.eu/extension/"
HIDDEN_COGS = {"Compatibility"}
OWNER = "Bot owner"

FEATURES = (
    "Components V2 interface everywhere",
    "Hybrid commands - every command works as `/slash` and `!prefix`",
    "Grouped slash commands (fits Discord's 100 command limit)",
    "Hot reload, dependency-aware extension loading",
    "Plugin registry with version / conflict / cycle checks",
    "Framework event hooks with circuit breakers",
    "No-code automations with chained actions, conditions and cooldowns",
    "Persistent cron task scheduler",
    "Full server backup & selective restore",
    "Shard monitor + multi-process cluster IPC",
    "Per-server prefixes and role-based command permissions",
    "Diagnostics: loop lag, error rate, health history",
    "Atomic file storage + SQLite (WAL) with migrations and recovery",
    "ZSync extension marketplace",
)

NEW_IN_V2 = (
    "Rewritten from the ground up as the `zdbf` package",
    "Every message is a Components V2 layout",
    "config.toml + pydantic validation, runtime overrides",
    "Single database with migrations (per-server files retired)",
    "Owner groups can be limited to development servers",
    "Python 3.12 - 3.14, discord.py 2.7",
    "Apache 2.0 license",
)

_OPTION_TYPES = {
    discord.AppCommandOptionType.string: "text",
    discord.AppCommandOptionType.integer: "whole number",
    discord.AppCommandOptionType.number: "number",
    discord.AppCommandOptionType.boolean: "yes / no",
    discord.AppCommandOptionType.user: "member",
    discord.AppCommandOptionType.channel: "channel",
    discord.AppCommandOptionType.role: "role",
    discord.AppCommandOptionType.mentionable: "member or role",
    discord.AppCommandOptionType.attachment: "file",
}
_CONVERTER_TYPES: tuple[tuple[type, str], ...] = (
    (bool, "yes / no"), (int, "whole number"), (float, "number"), (str, "text"),
    (discord.Member, "member"), (discord.User, "member"), (discord.Role, "role"),
    (discord.abc.GuildChannel, "channel"), (discord.Thread, "thread"), (discord.Attachment, "file"),
)
_BANNERS: dict[int, str | None] = {}


@dataclass
class Option:
    name: str
    kind: str
    required: bool
    default: str | None
    description: str
    choices: tuple[str, ...]


@dataclass
class Entry:
    command: commands.Command[Any, ..., Any]
    slash_name: str
    prefix_name: str
    description: str
    slash: bool
    access: str
    aliases: tuple[str, ...]

    def display(self, prefix: str) -> str:
        return f"/{self.slash_name}" if self.slash else f"{prefix}{self.prefix_name}"


@dataclass
class Category:
    name: str
    description: str
    entries: list[Entry]

    @property
    def owner_only(self) -> bool:
        return bool(self.entries) and all(e.access == OWNER for e in self.entries)


def _first_line(value: str | None) -> str:
    return (value or "").strip().split("\n")[0].strip()


def describe(cmd: commands.Command[Any, ..., Any]) -> str:
    return _first_line(cmd.description or cmd.short_doc or cmd.help) or "No description."


def has_slash(bot: ZDBFBot, cmd: commands.Command[Any, ..., Any]) -> bool:
    root = cmd.root_parent or cmd
    if getattr(root, "app_command", None) is None or not getattr(root, "with_app_command", True):
        return False
    guard = getattr(bot, "slash_guard", None)
    demoted = {d.name for d in guard.demoted.values()} if guard else set()
    return root.name not in demoted


def make_entry(bot: ZDBFBot, cmd: commands.Command[Any, ..., Any]) -> Entry:
    fallback = getattr(cmd, "fallback", None) if isinstance(cmd, commands.Group) else None
    return Entry(cmd, f"{cmd.qualified_name} {fallback}" if fallback else cmd.qualified_name, cmd.qualified_name,
                 describe(cmd), has_slash(bot, cmd), access_level(cmd), tuple(cmd.aliases))


def _app_params(cmd: commands.Command[Any, ..., Any]) -> dict[str, Any]:
    app = getattr(cmd, "app_command", None)
    fallback = getattr(cmd, "fallback", None)
    if isinstance(app, app_commands.Group) and fallback:
        app = app.get_command(fallback)
    return {p.name: p for p in app.parameters} if isinstance(app, app_commands.Command) else {}


def _converter_kind(converter: Any) -> tuple[str, tuple[str, ...]]:
    origin = typing.get_origin(converter)
    if origin is typing.Literal:
        return "choice", tuple(str(a) for a in typing.get_args(converter))
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(converter) if a is not type(None)]
        return _converter_kind(args[0]) if args else ("value", ())
    for kind, label in _CONVERTER_TYPES:
        if inspect.isclass(converter) and issubclass(converter, kind):
            return label, ()
    return str(getattr(converter, "__name__", "value")).lower(), ()


def _default(value: Any) -> str | None:
    if value is None or value is inspect.Parameter.empty or value == "":
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def options_of(cmd: commands.Command[Any, ..., Any]) -> list[Option]:
    app = _app_params(cmd)
    out = []
    for name, param in cmd.clean_params.items():
        ap = app.get(name)
        if ap is not None:
            kind = _OPTION_TYPES.get(ap.type, ap.type.name)
            choices = tuple(str(c.name) for c in ap.choices)
            description = ap.description
            display = ap.display_name
        else:
            kind, choices = _converter_kind(param.converter)
            description = param.description or ""
            display = param.displayed_name or name
        if description in ("…", "...", "-"):
            description = ""
        out.append(Option(display, "choice" if choices else kind, param.required,
                          None if param.required else _default(param.default), description, choices))
    return out


def usage_lines(entry: Entry, options: list[Option], prefix: str) -> list[str]:
    lines = []
    if entry.slash:
        parts = [f"{o.name}:<{o.kind}>" if o.required else f"[{o.name}]" for o in options]
        lines.append(" ".join([f"/{entry.slash_name}", *parts]))
    parts = [f"<{o.name}>" if o.required else f"[{o.name}]" for o in options]
    lines.append(" ".join([f"{prefix}{entry.prefix_name}", *parts]))
    return lines


async def collect(ctx: commands.Context[Any]) -> list[Category]:
    bot: ZDBFBot = ctx.bot
    buckets: dict[str, Category] = {}
    for command in bot.walk_commands():
        if command.hidden or command.cog_name in HIDDEN_COGS:
            continue
        if isinstance(command, commands.Group) and not getattr(command, "fallback", None):
            continue
        try:
            if not await command.can_run(ctx):
                continue
        except Exception:
            continue
        name = command.cog_name or "Other"
        if name not in buckets:
            cog = command.cog
            buckets[name] = Category(name, _first_line(cog.description) if cog else "", [])
        buckets[name].entries.append(make_entry(bot, command))
    for cat in buckets.values():
        cat.entries.sort(key=lambda e: e.slash_name)
    return sorted(buckets.values(), key=lambda c: (c.name != "General", c.owner_only, c.name.lower()))


async def resolve_banner(bot: ZDBFBot) -> str | None:
    configured = bot.config.settings.ui.help_banner.strip()
    if configured:
        return configured
    if bot.user is None:
        return None
    if bot.user.id not in _BANNERS:
        try:
            user = await bot.fetch_user(bot.user.id)
            _BANNERS[bot.user.id] = user.banner.url if user.banner else None
        except discord.HTTPException:
            _BANNERS[bot.user.id] = None
    return _BANNERS[bot.user.id]


def invite_url(bot: ZDBFBot) -> str | None:
    settings = bot.config.settings.ui
    app = getattr(bot, "application", None)
    if not settings.invite_button or app is None or not app.bot_public or bot.application_id is None:
        return None
    return discord.utils.oauth_url(bot.application_id, permissions=discord.Permissions(settings.invite_permissions),
                                   scopes=("bot", "applications.commands"))


def link_buttons(bot: ZDBFBot, *, repository: bool = True) -> list[ui.Button[Any]]:
    out = []
    if url := bot.config.settings.ui.support_url.strip():
        out.append(link_button("Support server", url))
    if url := invite_url(bot):
        out.append(link_button("Invite", url))
    if repository:
        out.append(link_button("Repository", REPO_URL))
    return out


def credits_view(bot: ZDBFBot) -> discord.ui.LayoutView:
    box = cards.card(
        "Credits",
        "Zoryx Discord Bot Framework is designed and maintained by **TheHolyOneZ**.",
        cards.sep(),
        cards.fields({
            "Author": f"TheHolyOneZ · [GitHub repository]({REPO_URL})",
            "System": "\n".join(f"{Glyph.BULLET} {f}" for f in FEATURES),
            "License": "Apache License 2.0 - see `LICENSE` and `NOTICE`. The ZSync Marketplace client is "
                       "covered by `LICENSE-MARKETPLACE`.",
        }),
        accent="brand",
        thumbnail=bot.user.display_avatar.url if bot.user else None,
        foot=f"{__version__} · Created by TheHolyOneZ",
    )
    box.add_item(row(link_button("Repository", REPO_URL), link_button("ZSync Marketplace", MARKETPLACE_URL)))
    return cards.static(box)


async def _send_credits(interaction: discord.Interaction[Any]) -> None:
    await interaction.response.send_message(view=credits_view(interaction.client), ephemeral=True)


def credits_button() -> discord.ui.Button[Any]:
    return button("Credits", _send_credits)


def _rank(entry: Entry, category: str, query: str, legacy: list[str]) -> int | None:
    name = entry.slash_name.lower()
    if name == query or entry.prefix_name.lower() == query or query in (a.lower() for a in entry.aliases):
        return 0
    if name.startswith(query) or any(part.startswith(query) for part in name.split()):
        return 1
    if query in name or query in legacy:
        return 2
    if query in entry.description.lower() or query in category.lower():
        return 3
    return None


class HelpView(BaseView):
    HOME_PER_PAGE = 5
    PER_PAGE = 6
    SUB_PER_PAGE = 5

    def __init__(self, bot: ZDBFBot, author_id: int, categories: list[Category], prefix: str, *,
                 banner: str | None = None) -> None:
        super().__init__(author_id=author_id, timeout=600)
        self.bot = bot
        self.categories = categories
        self.prefix = prefix
        self.banner = banner
        self.mode = "home"
        self.category: Category | None = None
        self.command: commands.Command[Any, ..., Any] | None = None
        self.query = ""
        self.results: list[Entry] = []
        self.note: str | None = None
        self.home_page = 0
        self.page = 0
        self.sub_page = 0
        self.history: list[tuple[Any, ...]] = []

    @property
    def entries(self) -> list[tuple[Category, Entry]]:
        return [(c, e) for c in self.categories for e in c.entries]

    def _state(self) -> tuple[Any, ...]:
        return (self.mode, self.category, self.command, self.query, self.results, self.note, self.page, self.sub_page)

    def _restore(self, state: tuple[Any, ...]) -> None:
        (self.mode, self.category, self.command, self.query, self.results, self.note, self.page,
         self.sub_page) = state

    def open_command(self, cmd: commands.Command[Any, ..., Any], *, remember: bool = True) -> None:
        if remember:
            self.history.append(self._state())
        self.mode, self.command, self.sub_page = "command", cmd, 0

    def search(self, query: str, *, remember: bool = True) -> None:
        if remember and self.mode != "search":
            self.history.append(self._state())
        query = query.strip().lower().removeprefix("/").removeprefix(self.prefix)
        ranked = []
        for cat, entry in self.entries:
            rank = _rank(entry, cat.name, query, [k for k, v in self.bot.legacy_aliases.items()
                                                  if v == entry.prefix_name]) if query else None
            if rank is not None:
                ranked.append((rank, entry.slash_name, entry))
        self.mode, self.query, self.page = "search", query, 0
        self.results = [e for _, _, e in sorted(ranked, key=lambda r: (r[0], r[1]))]

    def _go(self, mode: str, category: Category | None = None):
        async def cb(interaction: discord.Interaction[Any]) -> None:
            self.history.clear()
            self.mode, self.category, self.page, self.note = mode, category, 0, None
            await self.refresh(interaction)

        return cb

    def _open(self, cmd: commands.Command[Any, ..., Any]):
        async def cb(interaction: discord.Interaction[Any]) -> None:
            self.open_command(cmd)
            await self.refresh(interaction)

        return cb

    async def _back(self, interaction: discord.Interaction[Any]) -> None:
        if self.history:
            self._restore(self.history.pop())
        else:
            self.mode, self.category, self.command = "home", None, None
        await self.refresh(interaction)

    async def _search(self, interaction: discord.Interaction[Any]) -> None:
        async def done(modal_interaction: discord.Interaction[Any], values: dict[str, str]) -> None:
            self.note = None
            self.search(values["q"])
            await self.refresh(modal_interaction)

        await interaction.response.send_modal(FormModal("Search commands", [FormField(
            "q", "Command, keyword or old V1 name", placeholder="e.g. backup, prefix, roles", max_length=80,
            default=self.query or None)], done))

    async def _goto(self, interaction: discord.Interaction[Any], index: int) -> None:
        if self.mode == "home":
            self.home_page = index
        elif self.mode == "command":
            self.sub_page = index
        else:
            self.page = index
        await self.refresh(interaction)

    def _footer(self) -> ui.TextDisplay[Any]:
        name = self.bot.user.display_name if self.bot.user else "ZDBF"
        return cards.text(f"-# {name} · powered by ZDBF {__version__}")

    def _home(self) -> ui.Container[Any]:
        bot = self.bot
        box = cards.container(accent="brand")
        if self.banner:
            box.add_item(ui.MediaGallery(discord.MediaGalleryItem(self.banner)))
        name = bot.user.display_name if bot.user else "Help"
        app = getattr(bot, "application", None)
        about = _first_line(app.description if app else "") or "Everything I can do, in one place."
        total = sum(len(c.entries) for c in self.categories)
        head = (f"# {name}\n{cards.truncate(about, 300)}\n"
                f"-# {plural(total, 'command')} · {plural(len(self.categories), 'category')} · "
                f"prefix `{self.prefix}` or `/`")
        avatar = bot.user.display_avatar.url if bot.user else None
        box.add_item(cards.section(head, ui.Thumbnail(avatar)) if avatar else cards.text(head))
        box.add_item(cards.sep())
        pages = max(1, -(-len(self.categories) // self.HOME_PER_PAGE))
        self.home_page = min(self.home_page, pages - 1)
        box.add_item(cards.text(
            "### Getting started\n"
            f"{Glyph.BULLET} Every command works as `/command` and as `{self.prefix}command`.\n"
            f"{Glyph.BULLET} Open a category, or press **Search** to find a command by name or keyword.\n"
            f"{Glyph.BULLET} `{self.prefix}help <command>` jumps straight to one command.\n\n"
            "### Categories" + (f"\n-# Page {self.home_page + 1} of {pages}" if pages > 1 else "")))
        start = self.home_page * self.HOME_PER_PAGE
        for cat in self.categories[start:start + self.HOME_PER_PAGE]:
            tag = "  ·  bot owner" if cat.owner_only else ""
            box.add_item(cards.section(
                [f"**{cat.name}**  ·  {plural(len(cat.entries), 'command')}{tag}",
                 f"-# {cards.truncate(cat.description or f'Commands from {cat.name}', 150)}"],
                button("Open", self._go("category", cat), style=discord.ButtonStyle.primary)))
        if not self.categories:
            box.add_item(cards.text("*No commands are available to you here.*"))
        if pages > 1:
            box.add_item(nav_row(self.home_page, pages, self._goto))
        controls = [button("Search", self._search, style=discord.ButtonStyle.primary), credits_button(),
                    *link_buttons(bot)]
        box.add_item(row(*controls[:5]))
        box.add_item(self._footer())
        return box

    def _list(self, title: str, subtitle: str, entries: list[Entry], empty: str) -> ui.Container[Any]:
        box = cards.container(accent="primary")
        pages = max(1, -(-len(entries) // self.PER_PAGE))
        self.page = min(self.page, pages - 1)
        page_note = f" · page {self.page + 1} of {pages}" if pages > 1 else ""
        box.add_item(cards.text(f"## {title}\n-# {subtitle}{page_note}"))
        if self.note:
            box.add_item(cards.text(self.note))
        box.add_item(cards.sep())
        start = self.page * self.PER_PAGE
        for entry in entries[start:start + self.PER_PAGE]:
            tag = f"  ·  {entry.access.lower()}" if entry.access != "Everyone" else ""
            box.add_item(cards.section(
                [f"**`{entry.display(self.prefix)}`**{tag}", f"-# {cards.truncate(entry.description, 150)}"],
                button("Details", self._open(entry.command))))
        if not entries:
            box.add_item(cards.text(empty))
        if pages > 1:
            box.add_item(nav_row(self.page, pages, self._goto))
        box.add_item(cards.sep())
        box.add_item(row(button(f"{Glyph.PREV} All categories", self._go("home")),
                         button("Search", self._search, style=discord.ButtonStyle.primary)))
        box.add_item(self._footer())
        return box

    def _command(self) -> ui.Container[Any]:
        cmd = self.command
        assert cmd is not None
        entry = make_entry(self.bot, cmd)
        options = options_of(cmd)
        box = cards.container(accent="primary")
        full = (cmd.help or cmd.description or describe(cmd)).strip()
        box.add_item(cards.text(f"## {entry.display(self.prefix)}\n{cards.truncate(full, 900)}"))
        box.add_item(cards.sep())
        usage = "\n".join(usage_lines(entry, options, self.prefix))
        body = f"### Usage\n{cards.codeblock(usage)}"
        if options:
            lines = []
            for o in options:
                state = "required" if o.required else "optional" + (f", default `{o.default}`" if o.default else "")
                line = f"`{o.name}`  {o.kind} · {state}"
                if o.description:
                    line += f"\n-# {o.description}"
                if o.choices:
                    line += f"\n-# Choices: {', '.join(o.choices[:20])}"
                lines.append(line)
            body += "\n### Options\n" + "\n".join(lines)
        box.add_item(cards.text(cards.truncate(body, 2200)))
        box.add_item(cards.sep())
        details: dict[str, Any] = {"Category": cmd.cog_name or "Other", "Who can use it": entry.access}
        if entry.slash:
            details["Prefix"] = f"`{self.prefix}{entry.prefix_name}`"
        else:
            details["Slash"] = "not available (prefix only)"
        if cmd.aliases:
            details["Aliases"] = ", ".join(f"`{self.prefix}{a}`" for a in cmd.aliases)
        legacy = [old for old, new in self.bot.legacy_aliases.items() if new == cmd.qualified_name]
        if legacy:
            details["V1 names"] = ", ".join(f"`{self.prefix}{o}`" for o in legacy[:6])
        if cmd.cooldown:
            details["Cooldown"] = f"{cmd.cooldown.rate} per {cmd.cooldown.per:g} s"
        elif not isinstance(cmd, commands.Group) or getattr(cmd, "fallback", None):
            cfg = self.bot.config.settings.cooldowns
            details["Cooldown"] = f"{cfg.default_rate} per {cfg.default_per:g} s (default)"
        box.add_item(cards.text(cards.kv(details)))
        pages = 1
        if isinstance(cmd, commands.Group):
            subs = sorted((c for c in cmd.commands if not c.hidden), key=lambda c: c.name)
            pages = max(1, -(-len(subs) // self.SUB_PER_PAGE))
            self.sub_page = min(self.sub_page, pages - 1)
            box.add_item(cards.sep())
            box.add_item(cards.text(f"### Subcommands  ·  {len(subs)}"
                                    + (f"\n-# Page {self.sub_page + 1} of {pages}" if pages > 1 else "")))
            start = self.sub_page * self.SUB_PER_PAGE
            for sub in subs[start:start + self.SUB_PER_PAGE]:
                sub_entry = make_entry(self.bot, sub)
                box.add_item(cards.section(
                    [f"**`{sub_entry.display(self.prefix)}`**", f"-# {cards.truncate(sub_entry.description, 150)}"],
                    button("Details", self._open(sub))))
        if pages > 1:
            box.add_item(nav_row(self.sub_page, pages, self._goto))
        box.add_item(row(button(f"{Glyph.PREV} Back", self._back), button("All categories", self._go("home")),
                         button("Search", self._search, style=discord.ButtonStyle.primary)))
        box.add_item(self._footer())
        return box

    def build(self) -> None:
        self.clear_items()
        if self.mode == "category" and self.category is not None:
            cat = self.category
            subtitle = (cat.description or f"Commands from {cat.name}") + f" · {plural(len(cat.entries), 'command')}"
            box = self._list(cat.name, subtitle, cat.entries, "*No commands here.*")
        elif self.mode == "search":
            found = plural(len(self.results), "result")
            box = self._list("Search", f"“{self.query}” · {found}", self.results,
                             "*Nothing matches. Try a shorter word, or open a category.*")
        elif self.mode == "command" and self.command is not None:
            box = self._command()
        else:
            self.mode = "home"
            box = self._home()
        self.add_item(box)


async def _prefix(bot: ZDBFBot, ctx: commands.Context[Any]) -> str:
    return (await bot.guild_prefix(ctx.guild.id if ctx.guild else None))[0]


async def help_view(ctx: commands.Context[Any]) -> HelpView:
    bot: ZDBFBot = ctx.bot
    return HelpView(bot, ctx.author.id, await collect(ctx), await _prefix(bot, ctx), banner=await resolve_banner(bot))


def resolve_command(bot: ZDBFBot, name: str, prefix: str) -> commands.Command[Any, ..., Any] | None:
    clean = name.strip().removeprefix(prefix).removeprefix("/").strip()
    cmd = bot.get_command(clean)
    if cmd is None and (target := bot.legacy_aliases.get(clean.lower())):
        cmd = bot.get_command(target)
    if cmd is not None and isinstance(cmd.parent, commands.Group) and cmd.parent.qualified_name == clean:
        cmd = cmd.parent
    return cmd


async def open_help(ctx: commands.Context[Any], query: str | None = None) -> None:
    view = await help_view(ctx)
    if query:
        cmd = resolve_command(ctx.bot, query, view.prefix)
        allowed = False
        if cmd is not None and not cmd.hidden:
            try:
                allowed = await cmd.can_run(ctx)
            except Exception:
                allowed = False
        if allowed and cmd is not None:
            view.open_command(cmd, remember=False)
        else:
            view.search(query, remember=False)
            view.note = f"There is no command called `{query}`. These come closest:" if view.results else None
    await view.send(ctx)


async def send_group_help(ctx: commands.Context[Any]) -> None:
    assert ctx.command is not None
    view = await help_view(ctx)
    view.open_command(ctx.command, remember=False)
    await view.send(ctx)
