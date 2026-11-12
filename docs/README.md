# ZDBF V2 documentation

Everything about the Zoryx Discord Bot Framework, from the first start to writing your own
extensions. New here? Read the [README](../README.md) for an overview, then
[installation](guide/installation.md).

## User guide

For server owners and the people who host the bot. No programming needed.

| Page | What you learn |
|---|---|
| [Installation](guide/installation.md) | Create the Discord application, install, start, keep it running, update |
| [Configuration](guide/configuration.md) | `config.toml` and `.env`, every option, modules, owners, the status rotation |
| [Commands](guide/commands.md) | Every command with its options, who can use it and its V1 name |
| [Automations](guide/automations.md) | Welcome messages, role panels, tickets, XP, word filter, custom automations, conditions, variables |
| [Backup and restore](guide/backups.md) | What a backup holds, restoring with a preview, comparing, automatic backups |
| [Scheduler](guide/scheduler.md) | Cron tasks, expressions explained, time zones |
| [ZSync Marketplace](guide/marketplace.md) | Finding, checking and installing community extensions, key activation |
| [Web dashboard](guide/dashboard.md) | Installing the control panel, every page, capabilities, users and roles, hosting |
| [Running the bot](guide/operations.md) | Health checks, alerts, errors, the database, logs, sharding and clusters |
| [Migrating from V1](guide/migrating-from-v1.md) | Moving a V1 installation over and what changed |
| [Troubleshooting](guide/troubleshooting.md) | Common problems and their fixes |

## Developer guide

For people who write extensions or work on the framework.

| Page | What you learn |
|---|---|
| [Overview](dev/README.md) | Project layout, startup, how a command runs, services, tests, conventions |
| [Writing extensions](dev/extensions.md) | Commands, metadata, hot reload, config, permissions, scheduler, alerts, publishing |
| [Dashboard panels](dev/dashboard-panels.md) | Giving an extension its own page in the web dashboard |
| [Database and storage](dev/database.md) | Key/value storage, queries, transactions, migrations, atomic files |
| [UI kit](dev/ui-kit.md) | Components V2 cards, views, pagination, confirmations, modals |
| [Event hooks](dev/hooks-and-events.md) | Built-in events, your own events, circuit breakers |
| [Dashboard internals](dev/dashboard-internals.md) | How the web dashboard is built, adding actions and pages, local setup, tests |
| [Dashboard protocol](dev/dashboard-protocol.md) | Pairing, signed requests, channels, the security model |

## Elsewhere

- [CHANGELOG](../CHANGELOG.md): what changed in each version
- [CONTRIBUTING](../.github/CONTRIBUTING.md): how to send a pull request
- [SECURITY](../.github/SECURITY.md): how to report a vulnerability
- [ZSync Marketplace](https://zsync.eu/extension/): community extensions
