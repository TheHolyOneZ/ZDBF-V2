# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
from types import SimpleNamespace
from typing import Literal

import discord
import pytest
from discord import app_commands
from discord import components as dc
from discord.ext import commands

from zdbf.cogs.dashboard.actions import ActionContext, ActionError, catalogue, load_all
from zdbf.cogs.dashboard.actions import chat as chat_actions
from zdbf.cogs.dashboard.actions.commands import (
    app_restricted,
    build_app_arguments,
    build_invocation,
    clean_values,
    describe_commands,
    make_context,
    ordinary_member,
    restricted,
)
from zdbf.cogs.dashboard.client import topics_digest
from zdbf.cogs.dashboard.messages import serialize_components
from zdbf.core.bot import ACTING_AS_OWNER, ZDBFBot
from zdbf.core.permissions import guild_owner_or_owner, owner_only
from zdbf.ui import button, cards, link_button, row

CALLS: list[tuple] = []


@commands.hybrid_group(name="notes", description="Notes")
async def notes(ctx):
    pass


@notes.command(name="add", description="Add a note")
@app_commands.describe(title="Short title", text="The note")
async def notes_add(ctx, title: str, kind: Literal["info", "todo"] = "info", pinned: bool = False, *, text: str = ""):
    CALLS.append((title, kind, pinned, text))


@commands.hybrid_command(name="wipe", description="Remove everything")
@owner_only()
async def wipe(ctx):
    pass


@commands.hybrid_command(name="handover", description="Give the server away")
@guild_owner_or_owner()
async def handover(ctx):
    pass


@app_commands.command(name="lookup", description="Find a member")
@app_commands.describe(member="Who", reason="Why")
async def lookup(interaction: discord.Interaction, member: str, reason: str = "") -> None:
    pass


@app_commands.command(name="purge", description="Bulk delete")
@app_commands.default_permissions(manage_guild=True)
async def purge(interaction: discord.Interaction, amount: int) -> None:
    pass


def test_invocation_quotes_arguments_and_keeps_the_rest_raw():
    def build(values):
        return build_invocation("!", notes_add, clean_values(values))

    assert build({"title": "Shopping"}) == "!notes add Shopping"
    assert build({"title": "Two words", "kind": "todo"}) == '!notes add "Two words" todo'
    assert build({"title": 'say "hi"', "kind": "info", "pinned": True, "text": 'free text with "quotes" and  spaces'}) == \
        '!notes add "say \\"hi\\"" info true free text with "quotes" and  spaces'
    assert build({"title": "back\\slash here"}) == '!notes add "back\\\\slash here"'
    assert build({"title": "x", "kind": "", "pinned": None}) == "!notes add x"


def test_invocation_refuses_gaps_missing_and_unknown_options():
    with pytest.raises(ActionError, match="Fill in `title`"):
        build_invocation("!", notes_add, {})
    with pytest.raises(ActionError, match="cannot be skipped"):
        build_invocation("!", notes_add, {"title": "x", "pinned": "true"})
    with pytest.raises(ActionError, match="cannot be skipped"):
        build_invocation("!", notes_add, {"title": "x", "text": "hello"})
    with pytest.raises(ActionError, match="no option named `evil`"):
        build_invocation("!", notes_add, {"title": "x", "evil": "1"})
    with pytest.raises(ActionError, match="too long"):
        build_invocation("!", notes_add, {"title": "x" * 2000})
    with pytest.raises(ActionError):
        clean_values(["not", "a", "dict"])
    assert clean_values({"a": 5, "b": False, "c": "  ", "d": {"nested": 1}, "e": " x "}) == {"a": "5", "b": "false", "e": "x"}
    assert clean_values([]) == {} and clean_values(None) == {}, "PHP sends an empty object as an empty list"


def test_app_command_arguments_are_shell_quoted():
    assert build_app_arguments(lookup, {"member": "Mika", "reason": "it's late; rm -rf"}) == "Mika 'it'\"'\"'s late; rm -rf'"
    with pytest.raises(ActionError, match="Fill in `member`"):
        build_app_arguments(lookup, {})
    with pytest.raises(ActionError, match="no option named"):
        build_app_arguments(lookup, {"member": "x", "other": "y"})


@commands.hybrid_command(name="nuke", description="Delete the channels")
@commands.has_permissions(administrator=True)
async def nuke(ctx):
    pass


def _admin_check():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator

    return commands.check(predicate)


@commands.hybrid_command(name="restore", description="Restore a backup")
@_admin_check()
async def restore(ctx):
    pass


@commands.hybrid_command(name="rank", description="Your rank")
@commands.guild_only()
@commands.bot_has_permissions(embed_links=True)
async def rank(ctx):
    pass


def test_commands_with_any_real_check_count_as_restricted():
    assert restricted(wipe) and restricted(handover), "tagged owner levels"
    assert restricted(nuke), "discord.py permission checks"
    assert restricted(restore), "custom checks without an access label, like the backup commands"
    assert not restricted(notes_add) and not restricted(rank), "no checks, or only harmless ones"
    assert app_restricted(purge) and not app_restricted(lookup)
    load_all()
    actions = catalogue()
    assert actions["commands.run"] == "commands.run" and actions["commands.run_owner"] == "commands.owner"
    assert actions["chat.delete"] == "chat.send" and actions["chat.delete_any"] == "chat.moderate"
    assert actions["chat.pin"] == "chat.moderate" and actions["chat.history"] == "chat.read"
    assert actions["commands.list"] == "view" and actions["chat.tree"] == "chat.read"


def test_command_list_describes_options_for_the_form():
    tree = SimpleNamespace(walk_commands=lambda: [lookup, purge])
    bot = SimpleNamespace(walk_commands=lambda: [notes, notes_add, wipe], tree=tree, slash_guard=SimpleNamespace(demoted={}))
    listed = {c["name"]: c for c in describe_commands(bot)}
    assert set(listed) == {"notes add", "wipe", "lookup", "purge"}
    add = listed["notes add"]
    assert add["form"] == "prefix" and add["slash"] == "notes add" and not add["owner"]
    assert [(p["name"], p["kind"], p["required"], p["rest"]) for p in add["params"]] == [
        ("title", "text", True, False), ("kind", "choice", False, False), ("pinned", "yes / no", False, False),
        ("text", "text", False, True)]
    assert add["params"][1]["choices"] == ["info", "todo"] and add["params"][0]["description"] == "Short title"
    assert listed["wipe"]["owner"] and listed["wipe"]["access"] == "Bot owner"
    assert listed["lookup"]["form"] == "slash" and not listed["lookup"]["owner"] and listed["purge"]["owner"]
    assert [p["name"] for p in listed["lookup"]["params"]] == ["member", "reason"]


class _Role:
    def __init__(self, role_id: int, **permissions: bool) -> None:
        self.id = role_id
        self.permissions = discord.Permissions(**permissions)

    def __lt__(self, other: "_Role") -> bool:
        return self.id < other.id


def test_ordinary_member_has_only_everyone_permissions():
    everyone = _Role(100, send_messages=True)
    admin = _Role(200, administrator=True)
    guild = SimpleNamespace(id=100, owner_id=1, default_role=everyone, get_role=lambda rid: {200: admin}.get(rid))
    member = discord.Member.__new__(discord.Member)
    member.guild = guild
    member._user = SimpleNamespace(id=5)
    member._roles = discord.utils.SnowflakeList((200,))
    member.timed_out_until = None
    assert member.guild_permissions.administrator
    plain = ordinary_member(member)
    assert plain is not member and plain.id == 5
    assert not plain.guild_permissions.administrator and plain.guild_permissions.send_messages
    assert member.guild_permissions.administrator, "the real member is untouched"
    user = SimpleNamespace(id=5)
    assert ordinary_member(user) is user


async def test_acting_as_owner_applies_only_to_the_bot_inside_the_run():
    bot = SimpleNamespace(user=SimpleNamespace(id=5), _app_owner_ids={9}, config=SimpleNamespace(owner_ids=set()))
    bot.owner_id_set = {9}
    def is_owner(user):
        return ZDBFBot.is_owner(bot, user)

    me, stranger, owner = SimpleNamespace(id=5), SimpleNamespace(id=6), SimpleNamespace(id=9)
    assert not await is_owner(me) and await is_owner(owner)
    token = ACTING_AS_OWNER.set(True)
    try:
        assert await is_owner(me) and not await is_owner(stranger)
        inside = asyncio.create_task(is_owner(me))
    finally:
        ACTING_AS_OWNER.reset(token)
    assert await inside
    assert not await is_owner(me)
    assert not await asyncio.create_task(is_owner(me))


def test_card_messages_become_a_plain_tree():
    box = cards.card("Backup created", "**3** channels\n-# done", accent="success", foot="ZDBF")
    box.add_item(row(button("Restore", None, style=discord.ButtonStyle.danger), link_button("Docs", "https://example.com")))
    view = cards.static(box)
    nodes = [dc._component_factory(payload) for payload in view.to_components()]
    tree = serialize_components(nodes)
    assert [n["t"] for n in tree] == ["container"]
    container = tree[0]
    assert isinstance(container["accent"], int) and container["accent"] > 0
    kinds = [n["t"] for n in container["items"]]
    assert kinds[0] == "text" and "row" in kinds and "sep" in kinds
    texts = [n["content"] for n in container["items"] if n["t"] == "text"]
    assert any("Backup created" in t for t in texts) and any("3** channels" in t for t in texts)
    buttons = next(n for n in container["items"] if n["t"] == "row")["items"]
    assert [(b["label"], b["style"], b["url"]) for b in buttons] == [("Restore", "danger", None), ("Docs", "link", "https://example.com")]


def test_emoji_and_attachment_parsing():
    assert chat_actions.parse_emoji("👍") == "👍"
    custom = chat_actions.parse_emoji("<:party:123456789012345678>")
    assert custom.name == "party" and custom.id == 123456789012345678 and not custom.animated
    assert chat_actions.parse_emoji("a:spin:123456789012345678").animated
    for bad in ("", "thumbsup", "x" * 40, "<script>"):
        with pytest.raises(ActionError):
            chat_actions.parse_emoji(bad)

    def ctx(files):
        return ActionContext(None, None, "id", "chat.send", {"files": files})

    encoded = base64.b64encode(b"hello").decode()
    files = chat_actions._files(ctx([{"name": "../../etc/pass wd?.txt", "data": encoded}]))
    name = files[0].filename
    assert name == "_.._etc_pass wd_.txt" and "/" not in name and not name.startswith(".")
    assert files[0].fp.read() == b"hello"
    assert chat_actions._files(ctx(None)) == []
    for bad in ("x", [{"name": "a"}], [{"name": "a", "data": "not base64!"}], [{"name": "a", "data": encoded}] * 4):
        with pytest.raises(ActionError):
            chat_actions._files(ctx(bad))
    big = base64.b64encode(b"x" * (chat_actions.FILES_BYTES + 1)).decode()
    with pytest.raises(ActionError, match="limited"):
        chat_actions._files(ctx([{"name": "big.bin", "data": big}]))


def test_watch_topic_digest_matches_the_website():
    import hashlib

    assert topics_digest(set()) == hashlib.sha1(b"").hexdigest()
    assert topics_digest({"overview", "chat.10", "chat.9", "meta"}) == hashlib.sha1(b"chat.10,chat.9,meta,overview").hexdigest()


def test_only_requests_that_were_held_for_a_while_count_against_held_requests():
    from _dashboard import FakeCog

    from zdbf.cogs.dashboard.client import HOLD_PROBE, DashboardClient
    from zdbf.cogs.dashboard.link import Link

    client = DashboardClient(FakeCog(), Link(url="https://example.invalid/d", install_id="a", secret="f" * 64, bot_id="1"))
    for _ in range(5):
        client._note_pull_failure(True, 0.2)
        client._note_pull_failure(False, 30.0)
    assert client.hold_ok, "instant errors such as a 404 during an upload say nothing about held requests"
    client._note_pull_failure(True, HOLD_PROBE + 1)
    assert client.hold_ok
    client._note_pull_failure(True, HOLD_PROBE + 1)
    assert not client.hold_ok


async def test_a_built_invocation_runs_the_command_even_though_the_bot_wrote_the_message():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none(), help_command=None)
    bot.add_command(notes)
    me = SimpleNamespace(id=5, bot=True)
    bot._connection.user = me
    try:
        for values, expected in (
            ({"title": "Two words", "kind": "todo", "pinned": True, "text": 'keep "this" as  typed'},
             ("Two words", "todo", True, 'keep "this" as  typed')),
            ({"title": 'say "hi"'}, ('say "hi"', "info", False, "")),
        ):
            CALLS.clear()
            text = build_invocation("!", notes_add, clean_values(values))
            message = SimpleNamespace(content=text, _state=None, author=me, guild=None, channel=SimpleNamespace(id=1),
                                      attachments=[])
            ctx = make_context(bot, message, "!")
            assert ctx.command is notes and ctx.invoked_with == "notes" and ctx.prefix == "!"
            await bot.invoke(ctx)
            assert CALLS == [expected] and not ctx.command_failed
        other = make_context(bot, SimpleNamespace(content="?notes add x", _state=None), "!")
        assert other.command is None
    finally:
        bot.remove_command("notes")
