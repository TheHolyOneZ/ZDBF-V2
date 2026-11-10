# Contributing to ZDBF V2

Thanks for helping! Bug reports, docs fixes and pull requests are welcome.

## Setup

```bash
git clone https://github.com/TheHolyOneZ/ZDBF-V2
cd ZDBF-V2
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Before you open a PR

```bash
ruff check .          # lint (CI runs this)
pytest -q             # unit tests on Python 3.12, 3.13 and 3.14 in CI
python tools/selftest.py --deep   # optional: live test against YOUR test server
```

`tools/selftest.py` runs real commands on a Discord server. Use a dedicated
test server - `--deep` creates and deletes channels, roles and backups there.

## Guidelines

* Target Python 3.12+ and discord.py 2.7. Everything user-facing is a
  Components V2 layout - use the helpers in `zdbf/ui` (`cards`, `BaseView`,
  `Paginator`, `confirm`) instead of embeds.
* New commands belong in a group of the relevant module (Discord allows only
  100 top-level slash commands). Owner-only groups use `@owner_only()`.
* Store data in the database (`bot.db`) with a new entry in
  `zdbf/core/migrations/__init__.py` - never edit an applied migration.
* Keep V1 extension compatibility in mind (`bot.register_hook`, `bot.db`, …).
* Add a test in `tests/` for logic that doesn't need Discord.
* Run `python tools/gen_commands.py` when commands change.
* Every source file starts with an SPDX header. Files in `zdbf/marketplace/`
  use the marketplace license header instead.

## Licensing of contributions

By contributing you agree that your contribution is licensed under the
Apache License 2.0 (or, for `zdbf/marketplace/`, under LICENSE-MARKETPLACE).
