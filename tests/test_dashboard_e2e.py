# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import time
from pathlib import Path

import aiohttp
import pytest
from _dashboard import FakeCog

from zdbf.cogs.dashboard import actions
from zdbf.cogs.dashboard import protocol as p
from zdbf.cogs.dashboard.actions import action
from zdbf.cogs.dashboard.client import DashboardClient, LinkError, LinkRejected, pair

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard"
PHP = shutil.which("php")
PHP_ARGS = shlex.split(os.getenv("ZDBF_TEST_PHP_ARGS", ""))
MYSQL = os.getenv("ZDBF_TEST_MYSQL", "")
TABLES = ("audit", "watch", "events", "state", "commands", "nonces", "pairing", "bot", "limits", "sessions",
          "users", "roles", "meta")
PASSWORD = "correct horse battery"

pytestmark = pytest.mark.skipif(PHP is None, reason="php is not installed")


def _php(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([PHP, *PHP_ARGS, *args], capture_output=True, text=True, timeout=120, **kwargs)


def _drivers() -> set[str]:
    return set(_php("-r", 'echo implode(",", PDO::getAvailableDrivers());').stdout.split(","))


def test_php_files_have_no_syntax_errors():
    files = sorted([*WEB.rglob("*.php"), *(ROOT / "tests" / "dashboard").rglob("*.php"), ROOT / "tools" / "dashboard_dev_router.php"])
    assert len(files) > 30
    script = 'foreach (array_slice($argv, 1) as $f) { $o = []; exec(escapeshellarg(PHP_BINARY) . " -l " . escapeshellarg($f) . " 2>&1", $o, $c); if ($c) { echo implode("\\n", $o), "\\n"; exit(1); } }'
    result = _php("-r", script, *map(str, files))
    assert result.returncode == 0, result.stdout + result.stderr


def test_php_unit_checks():
    result = _php(str(ROOT / "tests" / "dashboard" / "php" / "run.php"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert " 0 failed" in result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_javascript_files_parse():
    files = sorted((WEB / "assets" / "js").rglob("*.js"))
    assert len(files) > 15
    for file in files:
        result = subprocess.run(["node", "--check", str(file)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, f"{file}: {result.stderr}"


def test_web_folder_ships_its_guards():
    for rel in (".htaccess", "app/.htaccess", "data/.htaccess", "nginx.example.conf", "index.php", "setup.php"):
        assert (WEB / rel).is_file(), rel
    for rel in ("app/.htaccess", "data/.htaccess"):
        assert "Require all denied" in (WEB / rel).read_text()
    for file in WEB.rglob("*.php"):
        text = file.read_text()
        assert "$_GET['token']" not in text and "$_REQUEST" not in text, file
    assert not [f for f in (WEB / "data").iterdir() if f.name != ".htaccess"], "runtime files must not be committed"


@pytest.fixture
def site(tmp_path):
    if os.name == "nt":
        pytest.skip("the PHP development server cannot hold requests in parallel on Windows")
    drivers = _drivers()
    if "sqlite" in drivers:
        database = {"driver": "sqlite"}
    elif MYSQL and "mysql" in drivers:
        host, port, name, user, password = MYSQL.split(":", 4)
        database = {"driver": "mysql", "db_host": host, "db_port": port, "db_name": name, "db_user": user, "db_pass": password}
        drop = "; ".join(f"DROP TABLE IF EXISTS zd_{t}" for t in TABLES)
        done = _php("-r", f'$p = new PDO("mysql:host={host};port={port};dbname={name}", {user!r}, {password!r}); $p->exec({drop!r});')
        assert done.returncode == 0, done.stderr
    else:
        pytest.skip("no PDO driver for the test (sqlite, or mysql with ZDBF_TEST_MYSQL)")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    data = tmp_path / "data"
    data.mkdir()
    env = {**os.environ, "ZDBF_DASHBOARD_DATA": str(data), "PHP_CLI_SERVER_WORKERS": "8", "ZDBF_DASHBOARD_HOLD": "2"}
    proc = subprocess.Popen([PHP, *PHP_ARGS, "-d", "opcache.enable=0", "-S", f"127.0.0.1:{port}", "-t", str(WEB),
                             str(ROOT / "tools" / "dashboard_dev_router.php")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 15
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                assert time.time() < deadline and proc.poll() is None, "the PHP server did not start"
                time.sleep(0.1)
        yield base, data, database
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


class Browser:
    def __init__(self, base: str) -> None:
        self.base = base
        self.http = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        self.csrf = ""

    async def close(self) -> None:
        await self.http.close()

    async def page(self, path: str, form: dict | None = None) -> tuple[int, str]:
        if form is None:
            async with self.http.get(f"{self.base}/{path}") as r:
                return r.status, await r.text()
        async with self.http.post(f"{self.base}/{path}", data=form, headers={"Origin": self.base}) as r:
            return r.status, await r.text()

    async def token(self, path: str) -> str:
        _, html = await self.page(path)
        return re.search(r'name="_token" value="([0-9a-f]+)"', html).group(1)

    async def login(self, username: str, password: str = PASSWORD) -> None:
        token = await self.token("login.php")
        _, html = await self.page("login.php", {"_token": token, "step": "password", "username": username, "password": password})
        assert 'id="app"' in html, "login failed"
        self.csrf = (await self.api("GET", "api/session.php"))[1]["csrf"]

    async def api(self, method: str, path: str, body: dict | None = None, *, csrf: bool = True) -> tuple[int, dict]:
        headers = {"X-CSRF-Token": self.csrf, "Origin": self.base} if csrf and method == "POST" else {}
        async with self.http.request(method, f"{self.base}/{path}", json=body if method == "POST" else None,
                                     headers=headers) as r:
            return r.status, json.loads(await r.text() or "{}")

    async def run(self, type_: str, args: dict | None = None, timeout: float = 20) -> dict:
        status, queued = await self.api("POST", "api/command.php", {"type": type_, "args": args or {}})
        assert status == 200, queued
        end = time.time() + timeout
        while time.time() < end:
            _, result = await self.api("GET", f"api/result.php?id={queued['id']}")
            if result["final"]:
                return result
        raise AssertionError("no result")


async def _signed(base: str, link, path: str, payload: dict, *, secret: str | None = None, timestamp: str | None = None,
                  nonce: str | None = None, install: str | None = None, tamper: bool = False) -> tuple[int, dict]:
    body, encoding = p.encode_body(payload)
    timestamp = timestamp or str(int(time.time()))
    nonce = nonce or secrets.token_hex(16)
    signature = p.request_signature(secret or link.secret, path, timestamp, nonce, body)
    if tamper:
        body += b" "
    headers = {"X-ZDBF-Install": install or link.install_id, "X-ZDBF-Timestamp": timestamp, "X-ZDBF-Nonce": nonce,
               "X-ZDBF-Encoding": encoding, "X-ZDBF-Signature": signature}
    async with aiohttp.ClientSession() as http, http.post(f"{base}/{path}", data=body, headers=headers) as r:
        return r.status, json.loads(await r.text() or "{}")


async def _until(check, timeout: float = 15.0, message: str = "condition not met"):
    end = time.time() + timeout
    while time.time() < end:
        value = await check() if asyncio.iscoroutinefunction(check) else check()
        if value:
            return value
        await asyncio.sleep(0.1)
    raise AssertionError(message)


async def test_pair_sync_command_and_attacks(site):
    base, data, database = site
    actions.load_all()
    saved = dict(actions.REGISTRY)
    ran: list[str] = []

    @action("test.write", "files.write")
    async def write(ctx):
        ran.append("write")
        return {"written": True}

    @action("test.reload", "extensions")
    async def reload(ctx):
        ran.append("reload")
        return {"reloaded": ctx.text("name")}

    @action("test.steps", "view")
    async def steps(ctx):
        await ctx.progress("Channels (3)")
        await asyncio.sleep(1.5)
        return {"steps": 1}

    owner = Browser(base)
    viewer = Browser(base)
    anonymous = Browser(base)
    client = None
    try:
        for path in ("data/config.php", "data/.htaccess", "app/Auth.php", "app/probe.txt", ".htaccess"):
            assert (await anonymous.page(path))[0] == 403, path
        status, _ = await anonymous.api("GET", "api/session.php")
        assert status == 401
        assert (await anonymous.api("POST", "api/bot/pair.php", {"code_id": "0" * 32}))[0] == 409

        async with anonymous.http.get(f"{base}/setup.php") as r:
            html, policy = await r.text(), r.headers["Content-Security-Policy"]
        module_map = re.search(r'<script type="importmap">(.*?)</script>', html).group(1)
        digest = base64.b64encode(hashlib.sha256(module_map.encode()).digest()).decode()
        assert f"script-src 'self' 'sha256-{digest}';" in policy and "unsafe-inline" not in policy
        imports = json.loads(module_map)["imports"]
        assert len(imports) > 40 and "/assets/js/core/live.js" in imports
        assert all(re.fullmatch(re.escape(plain) + r"\?v=[\w.-]+", stamped) for plain, stamped in imports.items())
        async with anonymous.http.get(f"{base}/api/session.php") as r:
            assert "script-src 'self';" in r.headers["Content-Security-Policy"]

        token = await owner.token("setup.php")
        key = re.search(r"return '([A-Z2-7-]+)'", (data / "setup-key.php").read_text()).group(1)
        form = {"_token": token, "probe": "ok", "username": "owner", "password": PASSWORD, "password2": PASSWORD, **database}
        _, html = await owner.page("setup.php", {**form, "setup_key": "AAAA-AAAA-AAAA-AAAA"})
        assert "That is not the setup key." in html
        _, html = await owner.page("setup.php", {**form, "setup_key": key})
        assert "Dashboard installed" in html, re.findall(r'field-error">([^<]+)', html)
        code = p.normalize_code(re.search(r"code:([A-Z2-7-]+)", html).group(1))
        assert not (data / "setup-key.php").exists()
        assert "Setup is complete" in (await owner.page("setup.php"))[1]
        assert code not in "".join(f.read_text(errors="ignore") for f in data.iterdir() if f.is_file() and f.suffix == ".php")

        with pytest.raises(LinkError, match="wrong or has expired"):
            await pair(base, "A" * 32, "123456789012345678")
        link = await pair(base, code, "123456789012345678")
        assert len(link.secret) == 64 and link.url == base
        with pytest.raises(LinkError):
            await pair(base, code, "123456789012345678")
        assert link.secret not in (data / "config.php").read_text()

        cog = FakeCog(capabilities=["view", "extensions", "files.write"], approval=[], idle_interval=15)
        cog.link = link
        client = cog.client = DashboardClient(cog, link)
        client.start()

        await owner.login("owner")

        async def has_meta():
            _, live = await owner.api("GET", "api/live.php?topics=meta&rev=0&wait=0")
            return live["state"].get("meta")

        meta = await _until(has_meta, message="the bot never reported")
        assert meta["data"]["actions"]["test.reload"] == "extensions"
        await _until(lambda: client.watch_active, message="the bot never learned that a browser is watching")

        started = time.time()
        result = await owner.run("test.reload", {"name": "tickets"})
        assert result["status"] == "done" and result["data"] == {"reloaded": "tickets"}
        assert time.time() - started < 5, "a command should arrive within seconds while a browser is watching"
        ping = await owner.run("system.ping")
        assert ping["status"] == "done" and "database_ms" in ping["data"]
        assert client.connected and client.stats["commands"] == 2

        queued = (await owner.api("POST", "api/command.php", {"type": "test.steps"}))[1]["id"]
        notes, since = [], "sent"
        for _ in range(60):
            _, step = await owner.api("GET", f"api/result.php?id={queued}&since={since}&note={notes[-1] if notes else ''}")
            if step["final"]:
                break
            since = step["status"]
            if step["note"] and step["note"] not in notes:
                notes.append(step["note"])
        assert notes == ["Channels (3)"] and step["status"] == "done"
        assert step["data"] == {"steps": 1} and step["note"] == ""

        assert (await owner.api("POST", "api/command.php", {"type": "test.reload"}, csrf=False))[0] == 403
        assert (await owner.api("POST", "api/command.php", {"type": "no.such.action"}))[0] == 404
        assert (await anonymous.api("POST", "api/command.php", {"type": "system.ping"}))[0] == 401

        nonce = secrets.token_hex(16)
        assert (await _signed(base, link, p.PULL_PATH, {"v": 1, "wait": False}, nonce=nonce))[0] == 200
        assert (await _signed(base, link, p.PULL_PATH, {"v": 1, "wait": False}, nonce=nonce))[1]["error"] == "replay"
        assert (await _signed(base, link, p.PUSH_PATH, {"v": 1}, secret="0" * 64))[1]["error"] == "auth"
        assert (await _signed(base, link, p.PUSH_PATH, {"v": 1}, tamper=True))[1]["error"] == "auth"
        assert (await _signed(base, link, p.PUSH_PATH, {"v": 1}, install="f" * 16))[1]["error"] == "auth"
        stale = await _signed(base, link, p.PUSH_PATH, {"v": 1}, timestamp=str(int(time.time()) - 600))
        assert stale[0] == 401 and stale[1]["error"] == "skew"
        forged = await _signed(base, link, p.PUSH_PATH, {"v": 1, "state": {"meta": {"actions": {}}}}, secret="1" * 64)
        assert forged[0] == 401
        assert (await owner.api("GET", "api/live.php?topics=meta&rev=0&wait=0"))[1]["state"]["meta"]["data"]["actions"]

        cog.settings.capabilities = ["view", "extensions"]
        refused = await owner.run("test.write")
        assert refused["status"] == "denied" and "files.write" in refused["message"]
        assert "write" not in ran and cog.audit.outcomes()[-1] == "refused"

        status, _ = await owner.api("POST", "api/users.php", {"action": "create", "username": "viewer", "password": PASSWORD,
                                                              "role_id": next(r["id"] for r in (await owner.api("GET", "api/roles.php"))[1]["roles"] if r["name"] == "Viewer")})
        assert status == 200
        await viewer.login("viewer")
        assert (await viewer.api("POST", "api/command.php", {"type": "test.reload", "args": {"name": "x"}}))[0] == 403
        assert (await viewer.api("GET", "api/users.php"))[0] == 403
        assert (await viewer.api("GET", "api/audit.php"))[0] == 403
        assert (await viewer.api("POST", "api/link.php", {"action": "unpair"}))[0] == 403
        assert (await viewer.api("POST", "api/roles.php", {"action": "create", "name": "Root", "capabilities": ["users.manage"]}))[0] == 403
        assert (await viewer.run("system.ping"))["status"] == "done"
        other = (await owner.api("POST", "api/command.php", {"type": "system.ping"}))[1]["id"]
        assert (await viewer.api("GET", f"api/result.php?id={other}"))[0] == 403
        assert ran == ["reload"]

        status, entries = await owner.api("GET", "api/audit.php?limit=50")
        logged = [e["action"] for e in entries["entries"]]
        assert status == 200 and {"setup.completed", "link.paired", "login", "user.created", "command"} <= set(logged)

        assert await client.unpair()
        assert (await owner.api("GET", "api/session.php"))[1]["bot"]["paired"] is False
        with pytest.raises(LinkRejected):
            await client.call(p.PUSH_PATH, {"v": 1})
        assert not await client._reject(LinkRejected("auth"), 2) and client.broken is None
        assert await client._reject(LinkRejected("auth"), 3)
        assert client.broken and "pair again" in cog.bot.alerted[0]
    finally:
        actions.REGISTRY.clear()
        actions.REGISTRY.update(saved)
        if client is not None:
            await client.stop()
        for browser in (owner, viewer, anonymous):
            await browser.close()
