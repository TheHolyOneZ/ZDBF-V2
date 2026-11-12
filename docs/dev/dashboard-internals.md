# Dashboard internals

How the ZDBF Dashboard is built, where its parts live, and how to change it: add a bot action,
add a page, run it on your machine and test it. The user guide is
[docs/guide/dashboard.md](../guide/dashboard.md), the wire protocol and security model are in
[dashboard-protocol.md](dashboard-protocol.md), and extension panels are in
[dashboard-panels.md](dashboard-panels.md).

- [The three parts](#the-three-parts)
- [Bot side: `zdbf/cogs/dashboard/`](#bot-side-zdbfcogsdashboard)
- [Web side: `dashboard/`](#web-side-dashboard)
- [Life of an action](#life-of-an-action)
- [Live state and events](#live-state-and-events)
- [Adding a bot action](#adding-a-bot-action)
- [Adding a page](#adding-a-page)
- [Running it locally](#running-it-locally)
- [Tests](#tests)
- [Conventions](#conventions)
- [Shipping changes](#shipping-changes)

## The three parts

```
Browser ──HTTPS──> Website (PHP + SQLite or MySQL) <──HTTPS── Bot (zdbf/cogs/dashboard)
          session,                                   signed,
          CSRF                                       outbound only
```

| Part | Code | Job |
|---|---|---|
| Bot | `zdbf/cogs/dashboard/` | Decides everything. Runs actions, enforces capabilities, approvals, the file sandbox and the audit log. Pushes state and events. |
| Website | `dashboard/*.php`, `dashboard/app/`, `dashboard/api/` | A mailbox with logins. Stores the bot's latest state, queues commands from browsers, hands them to the bot, returns results. Untrusted by the bot. |
| Browser app | `dashboard/assets/` | A single-page app in plain ES modules that reads state from the website and sends actions. |

The bot never accepts connections. It pulls commands and pushes results, so it works from a home PC
behind NAT.

## Bot side: `zdbf/cogs/dashboard/`

| File | Contents |
|---|---|
| `cog.py` | The `Dashboard` cog: `/dashboard` commands, start and stop of the link, log tail, panel cleanup on unload |
| `client.py` | `DashboardClient`: the pull loop, push loop and sampling loop, back-off, held requests |
| `protocol.py` | Signing and checking requests and responses, pairing proofs, constants such as `MAX_COMMAND_AGE` |
| `link.py` | The stored link (`data/dashboard/link.json`, owner-readable only) |
| `capabilities.py` | Capability names, defaults and the `Policy` (enabled, approval, locked) |
| `approvals.py` | Approval requests by DM with Approve, Approve for 15 minutes and Deny |
| `actions/` | The action registry and every action, one module per area |
| `state.py` | `StateHub`: the topics pushed to the website (`meta`, `overview`, `series`, `activity`, `guilds`...) |
| `logtail.py` | Live log lines, with secrets redacted |
| `messages.py` | Converts Discord messages (Components V2, embeds, mentions) for the chat page |
| `sandbox.py` | Path checks for file actions |
| `audit.py` | The bot-side audit log (`/dashboard audit`) |
| `export.py` | Builds the upload zip and the setup key |
| `panels.py` | The panel registry for extensions |

`actions/__init__.py` defines `Action`, `ActionContext`, the `@action` decorator and the
`Dispatcher` that checks and runs incoming commands. `load_all()` imports the action modules
listed in `MODULES` when the cog loads.

## Web side: `dashboard/`

```
dashboard/
  index.php, login.php, setup.php, recover.php, oauth.php   pages (each renders a shell, the app does the rest)
  api/
    bot/pair.php, bot/pull.php, bot/push.php                 called by the bot, signed
    live.php                                                 browser: held request for state and events
    command.php, result.php                                  browser: queue an action, wait for its result
    account, audit, link, roles, session, sessions, settings, users .php
  app/                                                       PHP classes (namespace Zdbf\Dashboard), denied to visitors
    bootstrap.php    loads config, sets headers, autoloads
    Auth, Session, Totp, OAuth, RateLimit, Roles             logins and permissions
    BotAuth, Pairing, Crypto                                 the bot link
    Queue, Feed, Audit                                       commands, state and events, the website audit log
    Db, Schema, Config, Setup, Http, View                    storage, setup, responses, page shells
  assets/
    css/      tokens.css (design tokens), base, shell, components, views, chat, tools, auth
    js/
      app.js        routes, navigation, shell
      core/         api.js (get, post, run), live.js (held requests), store.js (topics, session, can),
                    router.js, dom.js (h, mount, button), format.js, icons.js
      ui/           modal, toast, palette, shortcuts, select, editor, chart, motion, field (background), ...
      views/        one module per page
    vendor/   third-party scripts (bundled, no CDN)
    fonts/
    LICENSES.txt
  data/       created at setup: config.php, setup key, SQLite database. Denied to visitors.
  .htaccess, nginx.example.conf
```

There is no build step. The PHP needs 8.1+ with PDO (SQLite or MySQL), OpenSSL and, optionally,
zlib. The JavaScript runs as native ES modules in current browsers.

## Life of an action

Taking "reload an extension" from the Extensions page:

1. The view calls `run('extensions.reload', { name: 'shop' })` from `core/api.js`.
2. `api/command.php` checks the session and CSRF token, looks up the capability of
   `extensions.reload` in the action catalogue the bot last pushed (`meta.actions`), checks the
   user's role for it, checks that the bot has not switched it off, rate limits, and queues the
   command with the user's ID, name and role. It answers with a command ID.
3. The browser polls `api/result.php?id=...`, which waits for a result.
4. The bot's pull request (`api/bot/pull.php`, held open while someone watches) returns the command.
5. The `Dispatcher` drops it if it saw the ID before or if it is older than 120 seconds, checks the
   capability against the bot's own `Policy`, asks for approval by DM if needed, then runs the
   handler with a timeout.
6. The bot pushes the result (`api/bot/push.php`). Progress notes (`ctx.progress`) and
   "awaiting approval" are pushed on the way.
7. `api/result.php` returns it, `run()` resolves with `result.data` or throws with the error
   message, and the view updates.

Every step that is not a plain `view` is written to the website's audit log and to the bot's.

## Live state and events

**Topics** are snapshots the bot pushes when they change. `StateHub` collects them; a topic is
only sent when its content hash changed and someone watches it, except `meta`, `overview` and
`activity`, which are kept current even when nobody has the dashboard open.

```python
self.cog.state.register("my-topic", collector)     # async def collector() -> dict
self.cog.state.unregister("my-topic")
```

**Events** are a stream: chat messages, log lines, alerts. The bot sends them with
`cog.emit(topic, data)`, which only queues when a browser is watching that topic.

In the browser, a view subscribes and the app tells the website what to watch:

```js
import { subscribe, topic } from '../core/store.js';

const stop = subscribe('overview', (data) => render(data));   // called now with the current value, then on change
// return { destroy() { stop(); } } from the view
```

`live.js` keeps one held request to `api/live.php` per tab, with the watched topics in the query.
The website relays the watch list to the bot in the pull response, so the bot can switch between
fast pushes while someone watches and the slow `idle_interval` heartbeat when nobody does.

## Adding a bot action

1. Pick the module in `zdbf/cogs/dashboard/actions/` for the area, or add one and list it in
   `MODULES`.
2. Write the handler with the decorator:

   ```python
   from typing import Any

   from . import ActionContext, ActionError, action


   @action("system.echo", "view", timeout=15, summary=lambda a: f"echo {a.get('text', '')[:40]}")
   async def echo(ctx: ActionContext) -> dict[str, Any]:
       text = ctx.text("text", max_length=200)
       if text == "boom":
           raise ActionError("No explosions, please.")
       return {"echo": text, "by": ctx.user.get("name")}
   ```

   | Argument | Meaning |
   |---|---|
   | type | `area.verb`, lowercase, unique |
   | capability | One of the names in `capabilities.py`. Choose the narrowest that fits. |
   | `timeout` | Seconds before the action is stopped (default 60) |
   | `summary` | Text for the approval DM and the audit log, from the arguments |
   | `approval=False` | Never ask for approval, even if the capability is in the approval list. Only for actions that cannot change anything. |

3. Validate every argument with `ctx.text`, `ctx.integer`, `ctx.flag` or your own checks. The
   website is untrusted: assume any argument can be anything.
4. Raise `ActionError` for a message the user should see. Any other exception becomes a generic
   error with the type name, and the traceback goes to the bot log.
5. Anything touching files goes through `sandbox.py`. Anything touching settings must respect the
   protected keys (`[dashboard]`, `[modules] dashboard`, `bot.owner_ids`).
6. Add a test in `tests/test_dashboard_actions.py` or a neighbour: call the handler with a fake
   context, and check refusals as well as the happy path.

The catalogue the website uses is generated from the registry, so a new action needs no PHP change.
A **new capability** does: add it to `capabilities.py`, to the capability list and the built-in roles in
`dashboard/app/Roles.php`, to the defaults in `default_config.toml` and to the tables in the docs.

## Adding a page

1. Create `dashboard/assets/js/views/mypage.js`:

   ```js
   import { run } from '../core/api.js';
   import { button, h, mount } from '../core/dom.js';
   import { failure, toast } from '../ui/toast.js';

   export default function myPage(page, context) {
     const out = h('pre');
     page.append(
       h('header', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', { text: 'My page' }))),
       h('section', { class: 'card' }, h('div', { class: 'card-body' },
         button('Ping', { class: 'btn btn-primary', onClick: ping }), out)));

     async function ping() {
       try {
         const data = await run('system.ping');
         mount(out, h('code', { text: JSON.stringify(data) }));
       } catch (error) {
         failure(error);
       }
     }

     return { update(params) {}, destroy() {} };
   }
   ```

2. Register the route in `assets/js/app.js`:

   ```js
   router.register('mypage', { title: 'My page', icon: 'activity', group: 'Monitor', capability: 'view',
     load: () => import('./views/mypage.js') });
   ```

   `capability` hides the page from roles without it. `group` places it in the side rail
   (`Monitor`, `Control`, `Manage`, `Administration`, or `null` for none). Add a `g` shortcut in
   `ui/shortcuts.js` if it deserves one.

3. Build the DOM with `h()` and set text with `text:`, never `innerHTML` with data. The Content
   Security Policy forbids inline scripts and styles, so attach handlers in JavaScript and put
   styles in the CSS files, using the tokens from `tokens.css`.
4. Use the existing components: `card`, `page-head`, `btn`, `table`, `form-grid`, `field`, toasts,
   `confirm()` from `ui/modal.js`. Native `<select>` and checkboxes are restyled automatically.
5. Keep it working without motion: animations come from `ui/motion.js`, which respects
   reduced-motion and may load after the first paint.

For something an extension wants to show, prefer a [panel](dashboard-panels.md): it needs no web
changes at all.

## Running it locally

You need PHP 8.1+ with `pdo_sqlite` (or `pdo_mysql` and a MySQL/MariaDB database).

```bash
PHP_CLI_SERVER_WORKERS=8 ZDBF_DASHBOARD_DATA=/tmp/zdbf-dash ZDBF_DASHBOARD_HOLD=2 \
  php -d opcache.enable=0 -S 127.0.0.1:8090 -t dashboard tools/dashboard_dev_router.php
```

| Setting | Why |
|---|---|
| `tools/dashboard_dev_router.php` | Denies `app/` and `data/` like `.htaccess` does |
| `PHP_CLI_SERVER_WORKERS=8` | Held requests would otherwise block each other in the single-process server |
| `ZDBF_DASHBOARD_DATA` | Keeps the runtime data out of the repository |
| `ZDBF_DASHBOARD_HOLD=2` | Shortens held requests to 2 seconds |
| `-d opcache.enable=0` | Picks up PHP edits at once |

Then:

1. In `config.toml` set `[modules] dashboard = true` and restart the bot, or `/fw modules dashboard true`.
2. Run `/dashboard export`. The local server serves the repository's `dashboard/` folder, so you
   only need one file from the zip: copy `zdbf-dashboard/data/setup-key.php` into the folder you
   set as `ZDBF_DASHBOARD_DATA`. Setup reads the key from there.
3. Open `http://127.0.0.1:8090/setup.php`, choose SQLite, create the owner account.
4. Run the pair command it shows. Plain HTTP is accepted for `127.0.0.1` and `localhost` only.

Changes to JavaScript and CSS show on reload. Changes to the bot side need `/ext reload dashboard`
or a restart.

PHP's built-in server can hand two simultaneous connections to one worker, so a held request can
delay another by the hold time. Real web servers do not do this.

## Tests

```bash
pytest tests/test_dashboard_*.py        # protocol, sandbox, capabilities, actions, export, end to end
php tests/dashboard/php/run.php         # PHP checks, including the shared signing test vectors
```

`tests/test_dashboard_e2e.py` starts the PHP server, runs setup, pairs a bot, runs commands and
tries the attacks: wrong signature, replay, stale or tampered request, capability off, role
without permission. It is skipped without the SQLite PDO driver unless a MySQL database is given:

```bash
ZDBF_TEST_PHP_ARGS="-d extension=pdo_mysql" ZDBF_TEST_MYSQL="127.0.0.1:3306:zdbf_test:user:password" \
  pytest tests/test_dashboard_e2e.py
```

The signing code exists twice, in Python and PHP. Both are checked against the same test vectors;
change them together.

Test in a real browser as well as with scripts: header and policy problems (CSP, referrer,
cookies) only show up there.

## Conventions

- **No build step, no CDN.** Plain ES modules; third-party code is vendored into `assets/vendor/`
  and its licence listed in `assets/LICENSES.txt`.
- **The bot decides.** Never enforce a rule only in PHP or JavaScript. The website and browser may
  hide or disable things for comfort, but the bot must refuse on its own.
- **No secrets in URLs**, no error details to clients, prepared statements only.
- **Comment-free source**, like the Python side. Strip web files with the project's comment
  stripper before committing.
- **Cache-safe updates.** `View.php` writes an import map that gives every script a `?v=` stamp
  from its file time, and stylesheet links carry the same stamp, so an update loads fresh even
  behind a CDN. The policy names the import map's hash; do not add other inline blocks.
- **Theme and motion.** Colours come from `tokens.css` (dark and light). Every animation must have
  a reduced-motion path.

## Shipping changes

The bot builds the upload zip from the `dashboard/` folder of the installation it runs from
(`export.py`): every file except dotfiles other than `.htaccess`, `__pycache__`, `node_modules`,
`.git` and the contents of `data/`, plus a fresh setup key. Users update by running
`/dashboard export` again and uploading the files over the old ones, keeping `data/`.

Users often update the bot and the website at different times. When the protocol changes, bump
the protocol version (`VERSION`, sent as `v` in every push) and make the other side refuse an
unknown version with a clear message rather than misreading it.
