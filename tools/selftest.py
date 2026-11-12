# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import argparse
import asyncio
import copy
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord
from dotenv import load_dotenv

from zdbf.core.bot import ZDBFBot
from zdbf.core.config import Config
from zdbf.core.logging import setup_logging

DEFAULT_COMMANDS = [
    "help", "help backup create", "about", "ping", "stats", "stats shards", "stats commands",
    "settings view", "settings permissions list",
    "fw cache", "fw db", "fw integrity", "fw atomic-test", "fw alerts", "fw modules", "fw config validate",
    "fw config schema", "fw config show bot", "ext list",
    "diag overview", "diag history", "diag errors", "diag commands", "diag migrations",
    "eventhooks list", "eventhooks history", "plugins list", "plugins dependencies",
    "schedule list", "schedule preview 0 9 * * mon-fri", "hooks templates", "hooks list", "hooks create welcome",
    "hooks create leveling", "hooks create custom", "hooks conditions", "hooks leaderboard",
    "backup", "backup list", "backup audit", "backup schedule", "shard", "shard health", "shard details 0",
    "marketplace", "marketplace search tickets", "marketplace updates",
    "cachestats", "fw_diagnostics", "eh_list", "pr_list", "backuplist", "shardhealth", "serversettings", "framework",
]

log = logging.getLogger("selftest")


async def run(args: argparse.Namespace) -> int:
    config = Config().load()
    setup_logging(config.settings.logging)
    bot = ZDBFBot(config)
    failures: list[str] = []
    sent: list[discord.Message] = []
    done = asyncio.Event()

    @bot.listen("on_ready")
    async def _go() -> None:
        try:
            assert bot.user is not None
            guild = bot.get_guild(args.guild) if args.guild else bot.guilds[0]
            assert guild is not None, "bot is in no guild"
            channel = guild.get_channel(args.channel) if args.channel else next(
                c for c in guild.text_channels if c.permissions_for(guild.me).send_messages)
            assert isinstance(channel, discord.TextChannel)
            log.info("self test in #%s (%s)", channel.name, guild.name)
            actor = guild.owner or await guild.fetch_member(guild.owner_id)
            bot._app_owner_ids.add(actor.id)
            if (mp := bot.get_cog("Marketplace")) is not None:
                mp.accepted.add(actor.id)
            prefix = (await bot.guild_prefix(guild.id))[0]
            for command in args.commands or DEFAULT_COMMANDS:
                before = bot.metrics.errors_total
                msg = await channel.send(f"{prefix}{command}", allowed_mentions=discord.AllowedMentions.none())
                sent.append(msg)
                as_actor = copy.copy(msg)
                as_actor.author = actor
                ctx = await bot.get_context(as_actor)
                if ctx.command is None:
                    failures.append(f"{command}: command not found")
                    continue
                start = time.perf_counter()
                await bot.invoke(ctx)
                await asyncio.sleep(1.2)
                ms = (time.perf_counter() - start) * 1000
                if bot.metrics.errors_total > before:
                    err = bot.metrics.recent_errors[-1]
                    failures.append(f"{command}: {err.error}")
                    log.error("✗ %s (%s)", command, err.error)
                else:
                    log.info("✓ %s (%.0f ms)", command, ms)
            if args.deep:
                await deep_checks(bot, guild, channel, actor, failures)
            if not args.keep:
                await asyncio.sleep(2)
                me = guild.me
                await channel.purge(limit=len(sent) * 3 + 10, check=lambda m: m.author == me, bulk=True)
        except Exception as exc:
            failures.append(f"harness: {type(exc).__name__}: {exc}")
            log.exception("harness failed")
        finally:
            done.set()

    async with bot:
        runner = asyncio.create_task(bot.start(config.secrets.token))
        await asyncio.wait({runner, asyncio.create_task(done.wait())}, return_when=asyncio.FIRST_COMPLETED)
        await bot.close()
    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print("  ✗", f)
    else:
        print("all commands passed")
    return len(failures)


async def deep_checks(bot: ZDBFBot, guild: discord.Guild, channel: discord.TextChannel,
                      actor: discord.Member, failures: list[str]) -> None:
    async def check(name: str, coro) -> None:
        try:
            result = await coro
            log.info("✓ deep: %s%s", name, f" ({result})" if result else "")
        except Exception as exc:
            failures.append(f"deep {name}: {type(exc).__name__}: {exc}")
            log.exception("✗ deep: %s", name)

    async def backup_roundtrip() -> str:
        from zdbf.cogs.backup.restore import Restorer

        cog = bot.get_cog("Backup")
        temp = await guild.create_text_channel("zdbf-selftest-restore", topic="selftest")
        ok, text = await cog.create_backup(guild, actor.id, "selftest roundtrip", bypass_cooldown=True)
        assert ok, text
        entry = (await cog.storage.list(guild.id))[0]
        assert (await cog.storage.verify(entry))[0], "verify failed"
        snap = await cog.storage.load(entry)
        await temp.delete()
        await asyncio.sleep(1)
        dry = await Restorer(bot, guild, snap, {"channels"}, dry_run=True).run()
        assert any("zdbf-selftest-restore" in p for p in dry.planned), f"dry run did not plan the channel: {dry.planned}"
        real = await Restorer(bot, guild, snap, {"roles", "categories", "channels", "bot_settings"}).run()
        restored = discord.utils.get(guild.text_channels, name="zdbf-selftest-restore")
        assert restored is not None, f"channel not restored: {real.errors}"
        await restored.delete()
        view = await cog.diff_view(guild, entry, None)
        view.build()
        await channel.send(view=view)
        await cog.storage.delete(entry, actor.id)
        return f"created={real.created} skipped={real.skipped} failed={real.failed}"

    async def panels() -> str:
        from zdbf.cogs.automations.templates import TEMPLATES

        cog = bot.get_cog("Automations")
        role = await guild.create_role(name="zdbf-selftest-role")
        a = await cog.save_automation(guild=guild, template=TEMPLATES["button_roles"], name="selftest roles",
                                      config={"channel_id": channel.id, "roles": [role.id]}, author_id=actor.id)
        b = await cog.save_automation(guild=guild, template=TEMPLATES["tickets"], name="selftest tickets",
                                      config={"channel_id": channel.id, "support_role_id": role.id}, author_id=actor.id)
        assert a.config.get("panel_message_id") and b.config.get("panel_message_id"), "panel not posted"
        await cog.delete_automation(a)
        await cog.delete_automation(b)
        await role.delete()
        return "2 panels posted and removed"

    async def custom_automation() -> str:
        import copy as _copy

        from zdbf.cogs.automations.actions import CUSTOM

        cog = bot.get_cog("Automations")
        role = await guild.create_role(name="zdbf-selftest-custom")
        auto = await cog.save_automation(
            guild=guild, template=CUSTOM, name="selftest custom", author_id=actor.id,
            config={"trigger": "message", "match": "contains", "keyword": "zdbf-selftest-ping", "actions": [
                {"type": "send_message", "message": "pong for {display_name} · {math:6*7} · {date}", "card": True,
                 "title": "Custom automation"},
                {"type": "add_role", "role_id": role.id},
                {"type": "delay", "seconds": 1},
                {"type": "send_message", "message": "done after a wait", "card": False},
            ]})
        try:
            msg = await channel.send("zdbf-selftest-ping", allowed_mentions=discord.AllowedMentions.none())
            as_actor = _copy.copy(msg)
            as_actor.author = actor
            await cog.on_message(as_actor)
            await asyncio.gather(*cog._tasks)
            assert auto.run_count == 1, f"automation did not run cleanly: {auto.last_error}"
            member = await guild.fetch_member(actor.id)
            assert role in member.roles, "role was not added"
            await cog._flush()
            runs = await bot.db.fetchall("SELECT ok, error FROM automation_runs WHERE hook_id = ?", (auto.hook_id,))
            assert len(runs) == 1 and runs[0]["ok"], f"history: {[dict(r) for r in runs]}"
            history = await cog.history_view(auto, actor.id)
            history.build()
            await channel.send(view=history)
            return "2 messages, role added, 1 run in history"
        finally:
            await cog.delete_automation(auto)
            await role.delete()

    async def slash_budget() -> str:
        from discord import app_commands

        fakes = []
        for i in range(100):
            async def cb(interaction: discord.Interaction, value: int = 1, *, _i: int = i) -> None:
                await interaction.response.send_message(f"selftest fallback {_i} value={value}")

            cmd = app_commands.Command(name=f"zdbfselftest{i}", description="selftest", callback=cb)
            fakes.append(cmd)
            bot.tree.add_command(cmd)
        try:
            bot._prepare_tree()
            top = bot.tree.get_commands(type=discord.AppCommandType.chat_input)
            assert len(top) == 100, f"{len(top)} top-level commands"
            real = [c for c in top if not c.name.startswith("zdbfselftest")]
            lost = [d.name for d in bot.slash_guard.demoted.values() if not d.name.startswith("zdbfselftest")]
            assert not lost, f"real commands lost their slot: {lost}"
            demoted = [d for d in bot.slash_guard.demoted.values() if d.name.startswith("zdbfselftest")]
            assert demoted and all(d.fallback for d in demoted), "no prefix fallbacks"
            [c.to_dict(bot.tree) for c in top]
            name = demoted[-1].name
            msg = await channel.send(f"{(await bot.guild_prefix(guild.id))[0]}{name} 7",
                                     allowed_mentions=discord.AllowedMentions.none())
            as_actor = copy.copy(msg)
            as_actor.author = actor
            before = bot.metrics.errors_total
            await bot.invoke(await bot.get_context(as_actor))
            assert bot.metrics.errors_total == before, bot.metrics.recent_errors[-1].error
            return f"{len(real)} real commands kept, {len(demoted)} extra demoted, /{name} answered via prefix"
        finally:
            for cmd in fakes:
                bot.tree.remove_command(cmd.name)
                bot.slash_guard._stash.pop(("global", cmd.name), None)
            bot._prepare_tree()
            assert not bot.slash_guard.demoted, "demotions left behind"
            bot.slash_guard.newly_demoted = []

    async def backup_paging() -> str:
        from zdbf.cogs.backup.cog import Dashboard

        cog = bot.get_cog("Backup")
        seeded = [await cog.storage.save(guild.id, {"version": "2", "components": ["roles"], "roles": []},
                                         label=f"selftest seed {i:02d}", user_id=actor.id) for i in range(30)]
        try:
            view = Dashboard(cog, guild, await cog.storage.list(guild.id), actor.id)
            for page in (1, 2):
                view.page = page
                view.build()
                assert view.content_length() <= 4000 and view.total_children_count <= 40
                await channel.send(view=view)
            return f"{len(view.items)} backups, pages 2 and 3 sent"
        finally:
            for entry in seeded:
                await cog.storage.delete(entry, actor.id)

    async def scheduler() -> str:
        cog = bot.get_cog("Task Scheduler")
        tid = await cog.create_task_programmatic("selftest", "*/5 * * * *", "message", guild_id=guild.id,
                                                 channel_id=channel.id, creator_id=actor.id,
                                                 payload={"content": "scheduled selftest message", "title": "Selftest"})
        assert tid
        assert await cog.execute(cog.tasks[tid], manual=True), "execution failed"
        await cog.delete_task_programmatic(tid)
        return f"task {tid}"

    async def export() -> str:
        import io

        from zdbf.ui import cards

        box = cards.card("Export test", "file attachment in a V2 container")
        box.add_item(discord.ui.File("attachment://selftest.json"))
        await channel.send(view=cards.static(box), file=discord.File(io.BytesIO(b'{"ok": true}'), "selftest.json"))
        return None

    async def dashboard_actions() -> str:
        cog = bot.get_cog("Dashboard")
        if cog is None:
            return "dashboard module off, skipped"
        reads = [("system.ping", {}), ("extensions.list", {}), ("servers.list", {}), ("servers.detail", {"guild_id": guild.id}),
                 ("automations.catalogue", {}), ("automations.list", {"guild_id": guild.id}), ("scheduler.list", {}),
                 ("system.diagnostics", {}), ("system.shards", {}), ("system.hooks", {}), ("system.plugins", {}),
                 ("system.alerts", {}), ("presence.get", {}), ("tickets.list", {"guild_id": guild.id}),
                 ("commands.list", {}), ("chat.tree", {})]
        ran = 0
        for type_, args in reads:
            result = await cog.dispatcher.handle({"id": f"selftest-{time.time_ns()}", "type": type_, "args": args,
                                                  "user": {"id": "0", "name": "selftest"}, "issued_at": time.time()})
            if result is None or result["status"] == "denied":
                continue
            assert result["status"] == "done", f"{type_}: {result.get('error')}"
            ran += 1
        return f"{ran} read actions"

    for name, coro in (("dashboard actions", dashboard_actions()), ("backup round-trip", backup_roundtrip()), ("automation panels", panels()),
                       ("custom automation", custom_automation()), ("slash budget", slash_budget()),
                       ("backup paging", backup_paging()),
                       ("scheduler", scheduler()), ("file export", export())):
        await check(name, coro)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--guild", type=int)
    parser.add_argument("--channel", type=int)
    parser.add_argument("--keep", action="store_true", help="keep the messages instead of purging them")
    parser.add_argument("--deep", action="store_true", help="also run programmatic backup/restore, panel and "
                                                             "scheduler checks (creates and deletes test objects)")
    parser.add_argument("commands", nargs="*")
    load_dotenv()
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
