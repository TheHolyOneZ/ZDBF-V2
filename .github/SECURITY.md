# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

* Preferred: a private [GitHub Security Advisory](https://github.com/TheHolyOneZ/ZDBF-V2/security/advisories)
* Or contact [TheHolyOneZ](https://github.com/TheHolyOneZ) directly on GitHub

Include a description, the impact, steps to reproduce, the affected version
and (optionally) a suggested fix. You'll get an acknowledgement within 48 hours;
critical issues are targeted within 7 days. With your permission you'll be
credited in the fix.

## Supported versions

| Version | Supported |
|---|---|
| 2.x | ✅ |
| 1.x | ❌ (please migrate - see `docs/guide/migrating-from-v1.md`) |

## Built-in safeguards (V2)

* **Secrets stay in `.env`** (git-ignored). `/fw config show` redacts keys that
  look like tokens, secrets, passwords or API keys.
* **Owner detection** uses the Discord application owner / team plus
  `owner_ids`. Owner command groups are hidden from regular members
  (`administrator` default permission) and can be restricted to `dev_guild_ids`.
* **Cluster IPC** never sends the shared secret: authentication is an HMAC
  challenge-response, every frame is signed, stale (>60 s) and replayed frames
  are dropped, and secrets shorter than 16 characters are refused.
* **Atomic file writes** (temp file + fsync + replace) - no half-written files.
* **No `eval` / dynamic code** in automations; message templates only replace
  plain `{placeholders}` (no attribute access).
* **Allowed mentions** default to users only - `@everyone` / role pings from
  user-provided text are suppressed.
* **Marketplace installs** show a static scan (imports, risky calls) before a
  file is written, and are bot-owner only. The scan is informational - only
  install extensions you trust.

## Operator checklist

* Never commit `.env`, `data/` or `logs/`; rotate the token if it leaks.
* Enable only the privileged intents you need (`[bot].privileged_intents`).
* Give the bot role only the permissions its modules need.
* Keep `pip install -U -e .` current for discord.py security fixes.
