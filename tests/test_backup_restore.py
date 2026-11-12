# SPDX-License-Identifier: Apache-2.0
import asyncio
from types import SimpleNamespace

from zdbf.cogs.backup import restore as restore_module
from zdbf.cogs.backup.restore import Restorer


class Channel:
    def __init__(self, name, topic=None, slowmode_delay=0, nsfw=False, hang=False):
        self.name = name
        self.topic = topic
        self.slowmode_delay = slowmode_delay
        self.nsfw = nsfw
        self.overwrites = {}
        self.edits = []
        self.hang = hang

    async def edit(self, **kwargs):
        if self.hang:
            await asyncio.sleep(60)
        self.edits.append(kwargs)


def guild(channels):
    return SimpleNamespace(
        id=1, roles=[], categories=[], text_channels=channels, voice_channels=[], forums=[], stage_channels=[],
        default_role=SimpleNamespace(id=1), get_role=lambda _id: None, get_member=lambda _id: None,
        get_channel=lambda _id: None)


def snapshot(*channels):
    return {"guild": {"id": 1}, "text_channels": [
        {"name": name, "topic": topic, "slowmode_delay": 0, "nsfw": False, "overwrites": [], "position": i}
        for i, (name, topic) in enumerate(channels)]}


async def run(channels, snap, **options):
    restorer = Restorer(SimpleNamespace(), guild(channels), snap, {"channels"}, update_existing=True, **options)
    restorer._pause = lambda: asyncio.sleep(0)
    return await restorer.run()


async def test_unchanged_channels_are_not_edited():
    same = Channel("general", topic="hello")
    report = await run([same], snapshot(("general", "hello")))
    assert same.edits == [] and report.skipped == 1 and report.updated == 0


async def test_only_what_differs_is_sent():
    changed = Channel("general", topic="old")
    report = await run([changed], snapshot(("general", "new")))
    assert changed.edits == [{"reason": "ZDBF backup restore", "topic": "new"}]
    assert report.updated == 1 and report.failed == 0


async def test_preview_counts_changes_without_editing():
    changed = Channel("general", topic="old")
    report = await run([changed], snapshot(("general", "new")), dry_run=True)
    assert changed.edits == [] and report.updated == 1


async def test_a_rate_limited_change_is_skipped_and_the_restore_goes_on(monkeypatch):
    monkeypatch.setattr(restore_module, "CALL_TIMEOUT", 0.05)
    stuck = Channel("general", topic="old", hang=True)
    fine = Channel("news", topic="old")
    steps = []

    async def progress(text):
        steps.append(text)

    report = await run([stuck, fine], snapshot(("general", "new"), ("news", "new")), progress=progress)
    assert stuck.edits == [] and fine.edits == [{"reason": "ZDBF backup restore", "topic": "new"}]
    assert report.failed == 1 and report.limited == 1 and report.updated == 1
    assert "rate limiting" in report.errors[0] and report.errors[0].startswith("#general")
    assert steps == ["Channels (2)"]
