# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys

import discord
from dotenv import load_dotenv

from . import __version__
from .core.config import Config, ConfigError
from .core.logging import setup_logging

log = logging.getLogger("zdbf")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="zdbf", description="Run a ZDBF V2 bot.")
    parser.add_argument("--config", help="path to config.toml (default: ./config.toml or $ZDBF_CONFIG)")
    parser.add_argument("--env", default=".env", help="path to the .env file (default: ./.env)")
    parser.add_argument("--check", action="store_true", help="validate the configuration and exit")
    parser.add_argument("--version", action="version", version=f"ZDBF {__version__} (discord.py {discord.__version__})")
    return parser.parse_args(argv)


async def _run(config: Config) -> int:
    from .core.bot import ZDBFBot

    bot = ZDBFBot(config)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)

    async with bot:
        runner = asyncio.create_task(bot.start(config.secrets.token))
        waiter = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({runner, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if waiter in done:
            log.info("signal received")
        else:
            waiter.cancel()
        if not bot.is_closed():
            await bot.close()
        if runner in done and (exc := runner.exception()) is not None:
            raise exc
        runner.cancel()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv(args.env)
    config = Config(args.config)
    created = config.ensure_exists()
    try:
        config.load()
    except ConfigError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    if args.check:
        print(f"✓ {config.path} is valid")
        print("  token:", "set" if config.secrets.token else "MISSING (DISCORD_TOKEN in .env)")
        return 0 if config.secrets.token else 1

    setup_logging(config.settings.logging)
    log.info("ZDBF %s · discord.py %s · Python %s", __version__, discord.__version__, sys.version.split()[0])
    if created:
        log.warning("created a default %s - review it and restart if needed", config.path)
    if not config.secrets.token:
        log.critical("DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token.")
        return 1

    try:
        return asyncio.run(_run(config))
    except discord.PrivilegedIntentsRequired:
        log.critical(
            "Discord rejected the privileged intents %s. Enable them in the Developer Portal "
            "(Bot -> Privileged Gateway Intents) or remove them from [bot].privileged_intents.",
            config.settings.bot.privileged_intents,
        )
    except discord.LoginFailure:
        log.critical("Login failed - the DISCORD_TOKEN in .env is invalid.")
    except KeyboardInterrupt:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
