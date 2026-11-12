# SPDX-License-Identifier: Apache-2.0
import datetime as dt
from types import SimpleNamespace

import pytest

from zdbf.cogs.automations import transcripts as tr


def record(channel_id: int, closed: float, messages: int = 2) -> dict:
    return {
        "guild_id": "111111", "guild_name": "Guild", "channel_id": str(channel_id), "channel_name": "ticket-alex",
        "automation": "abcd", "opened_at": closed - 60, "closed_at": closed, "closed_by": "Mod",
        "owner": {"id": "222222", "name": "Alex"},
        "messages": [{"id": str(i), "at": closed - 30 + i, "author": {"id": "222222", "name": "Alex", "bot": False},
                      "content": f"line {i}\nsecond", "attachments": [{"name": "a.png", "url": "https://x/a.png", "size": 1}],
                      "embeds": ["Card"], "edited": None} for i in range(messages)],
    }


async def test_store_saves_lists_loads_and_deletes(tmp_path):
    store = tr.TranscriptStore(tmp_path)
    first = await store.save(record(123456, 1_800_000_000))
    await store.save(record(654321, 1_800_000_100, messages=5))
    listed = await store.list(111111)
    assert [e["channel_id"] for e in listed] == ["654321", "123456"] and listed[0]["messages"] == 5
    loaded = await store.load(111111, first["id"])
    assert loaded["messages"][0]["content"] == "line 0\nsecond"
    assert await store.load(111111, "../../etc") is None
    assert await store.delete(111111, first["id"]) and not await store.delete(111111, first["id"])
    assert [e["id"] for e in await store.list(111111)] == [f"654321-{1_800_000_100}"]


async def test_store_keeps_only_the_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "KEEP_PER_GUILD", 3)
    store = tr.TranscriptStore(tmp_path)
    for i in range(5):
        await store.save(record(100000 + i, 1_800_000_000 + i))
    kept = await store.list(111111)
    assert len(kept) == 3 and len(list((tmp_path / "111111").glob("*.json.gz"))) == 3


def test_text_rendering():
    text = tr.render_text(record(123456, 1_800_000_000))
    assert "Ticket #ticket-alex in Guild" in text and "Opened by Alex" in text and "Closed by Mod" in text
    assert "  line 0\n  second" in text and "[file] a.png https://x/a.png" in text and "[card] Card" in text


class FakeChannel:
    def __init__(self) -> None:
        self.id = 123456
        self.name = "ticket-alex"
        self.created_at = dt.datetime(2027, 1, 1, tzinfo=dt.UTC)
        self.guild = SimpleNamespace(id=111111, name="Guild", get_member=lambda i: SimpleNamespace(display_name="Alex"))
        self.deleted = None

    def history(self, limit, oldest_first):
        async def gen():
            yield SimpleNamespace(id=1, created_at=self.created_at, author=SimpleNamespace(id=222222, display_name="Alex", bot=False),
                                  content="help", attachments=[], embeds=[], edited_at=None)
        return gen()

    async def delete(self, reason):
        self.deleted = reason


@pytest.mark.parametrize("save", [True, False])
async def test_close_saves_when_enabled_and_deletes_the_channel(tmp_path, save):
    state = {(123456, "ticket_owner"): 222222, (222222, "open_ticket"): 123456}

    async def state_get(auto, scope, key, default=None):
        return state.get((scope, key), default)

    async def state_delete(auto, scope, key):
        state.pop((scope, key), None)

    cog = SimpleNamespace(runtime=SimpleNamespace(state_get=state_get, state_delete=state_delete, channel=lambda v: None),
                          transcripts=tr.TranscriptStore(tmp_path))
    auto = SimpleNamespace(hook_id="abcd", config={"transcripts": save})
    channel = FakeChannel()
    summary = await tr.close_ticket(cog, auto, channel, "Mod", delay=0)
    assert channel.deleted == "Ticket closed by Mod" and state == {}
    saved = await cog.transcripts.list(111111)
    if save:
        assert summary["messages"] == 1 and saved[0]["owner"] == {"id": "222222", "name": "Alex"}
    else:
        assert summary is None and saved == []
