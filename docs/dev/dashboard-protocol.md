# Dashboard protocol and security model

The contract between a ZDBF bot and its ZDBF Dashboard website: who trusts whom, how they pair,
how every request is signed, and which rules each side enforces. Change any of this only together
with both implementations (`zdbf/cogs/dashboard/protocol.py` and `client.py` on the bot,
`dashboard/app/BotAuth.php`, `Pairing.php` and `Crypto.php` on the website) and the shared test
vectors.

- [Roles](#roles)
- [Direction of traffic](#direction-of-traffic)
- [Pairing](#pairing)
- [Signed requests](#signed-requests)
- [Channels](#channels)
- [What the bot enforces](#what-the-bot-enforces)
- [What the website enforces](#what-the-website-enforces)
- [If the website is compromised](#if-the-website-is-compromised)

## Roles

| Part | Runs on | Trust |
|---|---|---|
| Bot | your bot host (PC, VPS, container) | trusted; enforces every rule itself |
| Website | any PHP 8.1+ web host | untrusted by the bot; assumed to be the first thing an attacker reaches |
| Browser | the admin's device | authenticated by the website |

The bot and the website are expected to run on different machines and networks.

## Direction of traffic

```
Browser ──HTTPS──> Website (PHP + database) <──HTTPS── Bot
```

The bot only makes outbound HTTPS requests to the website. The website never connects to the bot.
The bot host needs no open port, no public address and no firewall change. The website is a
mailbox: the browser leaves commands in a queue, the bot collects them and posts the results back.

HTTPS is required. Plain HTTP is accepted only for loopback addresses (`127.0.0.1`, `localhost`,
`::1`), for local testing.

## Pairing

1. `setup.php` creates the install and shows a one-time pairing code: 32 characters (160 bits),
   valid for 10 minutes, five attempts.
2. The bot owner runs `/dashboard pair <url> <code>` in Discord.
3. The bot sends `code_id` (a one-way hash of the code), a random `bot_nonce` and
   `proof = HMAC-SHA256(code, "zdbf-pair-proof\n" + bot_nonce + "\n" + bot_id)`.
4. The website checks the proof and answers with `install_id`, a random `server_nonce` and its own
   proof over both nonces, which the bot checks.
5. Both sides derive the shared secret:
   `HMAC-SHA256(code, "zdbf-dashboard-secret-v1\n" + bot_nonce + "\n" + server_nonce + "\n" + install_id)`.

Neither the code nor the 256-bit secret is transmitted. The code is deleted after use. The bot keeps
the secret in `data/dashboard/link.json` (owner-readable only); the website keeps it encrypted
(AES-256-GCM) in its database. Secrets never appear in a URL.

## Signed requests

Every request from the bot after pairing is a `POST` with these headers:

| Header | Value |
|---|---|
| `X-ZDBF-Install` | the install id |
| `X-ZDBF-Timestamp` | Unix time in seconds |
| `X-ZDBF-Nonce` | 32 random hex characters |
| `X-ZDBF-Encoding` | `gzip` or `identity` (how the body is encoded) |
| `X-ZDBF-Signature` | `HMAC-SHA256(secret, "POST\n" + path + "\n" + timestamp + "\n" + nonce + "\n" + sha256(body))` |

`path` is the endpoint relative to the dashboard folder, for example `api/bot/push.php`. The hash
covers the body exactly as sent.

The website rejects a request when the signature is wrong, the timestamp is more than 60 seconds
off, or the nonce was seen before. Signatures are compared in constant time. Failed attempts are
rate limited per address.

Responses are signed too:
`HMAC-SHA256(secret, "RESP\n" + path + "\n" + request_nonce + "\n" + timestamp + "\n" + sha256(body))`.
The bot ignores any response that is unsigned, stale or signed for a different request.

## Channels

| Endpoint | Purpose |
|---|---|
| `api/bot/pull.php` | The bot asks for queued commands. While a browser is watching, the website holds the request for up to about 20 seconds and answers the moment a command arrives. With nobody watching, the bot asks every 30 to 60 seconds. |
| `api/bot/push.php` | The bot sends state (only topics that changed and that somebody is watching), events (chat messages, log lines, alerts) and command results. Bodies are gzip-compressed. |

If a web host cuts held requests short, the bot and the browser fall back to short polling.

The browser reads through `api/live.php` (held the same way) and sends actions to
`api/command.php`, then waits for the result by command id.

## What the bot enforces

The website can ask for anything. The bot decides. These rules live on the bot host and cannot be
changed from the website:

- **Capabilities.** Every action belongs to a capability. Only capabilities listed in
  `[dashboard] capabilities` run. `/dashboard capabilities` changes the list from Discord (bot
  owner only).

  | Capability | Covers | Default |
  |---|---|---|
  | `view` | status, statistics, lists | on |
  | `logs` | live log tail | on |
  | `chat.read` | read channels the bot can see | on |
  | `chat.send` | send, edit and delete the bot's own messages, react | on |
  | `commands.run` | run commands with the rights of an ordinary member: the command's own checks refuse anything else | on |
  | `extensions` | load, unload, reload | on |
  | `files.read` | read files inside the allowed folders | on |
  | `automations`, `scheduler`, `settings`, `backups`, `presence` | manage those systems | on |
  | `chat.moderate` | delete other members' messages, pin | off |
  | `database` | read-only database browser | off |
  | `files.write` | create, change, rename, delete files | off, needs approval |
  | `config` | change `config.toml` and runtime overrides | off, needs approval |
  | `marketplace` | install extensions and Python packages | off, needs approval |
  | `commands.owner` | run commands with the rights of the bot owner | off, needs approval |
  | `backups.restore` | restore a server backup | off, needs approval |
  | `guilds.leave` | make the bot leave a server | off, needs approval |
  | `system` | shut the bot down | off, needs approval |

- **Approval in Discord.** A capability listed in `[dashboard] approval` waits for the bot owner to
  press Approve in a direct message. The message names the dashboard user, the action and a summary.
  "Approve for 15 minutes" covers further actions of the same capability by the same user.
- **One run per command.** Each command id runs once. Commands older than 120 seconds are dropped.
- **File sandbox.** File actions work only inside `[dashboard] file_roots` (`extensions/` by
  default). Paths are resolved to real paths; `..` and symlinks that leave a root are rejected.
  `.env` files, databases, `data/dashboard/`, the ZSync key, `.git/` and `.local/` are always
  denied. Sizes are limited, writes are atomic, and replaced or deleted files are kept in a local
  trash folder.
- **Protected settings.** Dashboard actions can never change the `[dashboard]` section, the
  `dashboard` module switch, `bot.owner_ids` or `.env`. Built-in modules cannot be loaded or unloaded
  from the website.
- **Log redaction.** The bot token and the IPC secret, and anything shaped like a Discord token, are
  replaced before a log line is sent to the website.
- **Audit log.** Every action the bot runs or refuses is recorded on the bot host with the dashboard
  user, the action and the outcome (`/dashboard audit`).
- **Lock.** `/dashboard lock` switches the link to view-only at once.

## What the website enforces

- **Accounts.** Local accounts use Argon2id (bcrypt where Argon2 is unavailable), optional TOTP with
  recovery codes, and rate limiting with lockout. Discord login is optional and limited to invited
  Discord accounts and the bot's owners.
- **Sessions.** Stored in the database; the cookie is `HttpOnly`, `Secure`, `SameSite=Strict` and
  rotated on login. Every write needs a CSRF token header and a same-origin request.
- **Roles.** Owner, Admin, Operator, Viewer and custom roles map to the capability names above. A
  role can never do more than the bot allows.
- **Storage.** Prepared statements only. Everything the website writes lives in `data/`, which is
  denied to visitors. Setup checks from the browser that `data/` and `app/` are not reachable and
  refuses to continue if they are.
- **Browser hardening.** A strict Content Security Policy (no inline code, no third-party
  hosts), HSTS, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, a minimal
  Permissions-Policy. The one inline block on a page is the import map, a list of script
  addresses that holds no code; the policy names its exact SHA-256 hash, so nothing else inline
  can run. No error details are sent to clients.
- **Plugins.** Extensions add dashboard panels as declared blocks (statistics, tables, forms) with
  handlers that run in the bot. They cannot add HTML, JavaScript or PHP to the website.

## If the website is compromised

An attacker who controls the web host can read what the bot sent there and can queue commands. They
are still limited to the enabled capabilities, cannot pass an approval, cannot change the capability
list, cannot reach files outside the sandbox and leave an audit trail on the bot host. Run
`/dashboard lock`, then `/dashboard unpair`, and pair again after cleaning the host.
