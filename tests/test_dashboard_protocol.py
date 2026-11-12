# SPDX-License-Identifier: Apache-2.0
import pytest
from _dashboard import VECTORS as V

from zdbf.cogs.dashboard import protocol as p
from zdbf.cogs.dashboard.capabilities import NAMES, Policy
from zdbf.core.config import Config, ConfigError, DashboardSettings, Settings


def test_pairing_and_signature_vectors():
    assert p.code_id(V["code"]) == V["code_id"]
    assert p.pair_proof(V["code"], V["bot_nonce"], V["bot_id"]) == V["proof"]
    assert p.pair_ack(V["code"], V["bot_nonce"], V["server_nonce"], V["install_id"]) == V["ack"]
    secret = p.derive_secret(V["code"], V["bot_nonce"], V["server_nonce"], V["install_id"])
    assert secret == V["secret"]
    assert p.request_signature(secret, p.PUSH_PATH, "1700000000", "a" * 32, b'{"v":1}') == V["request"]
    assert p.response_signature(secret, p.PUSH_PATH, "a" * 32, "1700000001", b'{"ok":true}') == V["response"]


def test_signature_covers_every_part():
    base = (V["secret"], p.PUSH_PATH, "1700000000", "a" * 32, b"{}")
    good = p.request_signature(*base)
    assert p.request_signature(V["secret"], p.PULL_PATH, *base[2:]) != good
    assert p.request_signature(*base[:2], "1700000001", *base[3:]) != good
    assert p.request_signature(*base[:3], "b" * 32, base[4]) != good
    assert p.request_signature(*base[:4], b"{} ") != good
    assert p.request_signature("0" * 64, *base[1:]) != good
    with pytest.raises(p.ProtocolError):
        p.request_signature("short", *base[1:])


def test_code_and_url_normalisation():
    assert p.normalize_code("abcd-efgh ijkl-mnop-qrst-uvwx-yz23-4567") == V["code"]
    for bad in ("", "ABCD", "A" * 31 + "1", "A" * 33):
        with pytest.raises(p.ProtocolError):
            p.normalize_code(bad)
    assert p.normalize_url("https://Example.com/dash/") == "https://Example.com/dash"
    assert p.normalize_url("https://example.com/dash/setup.php") == "https://example.com/dash"
    assert p.normalize_url("http://127.0.0.1:8090/") == "http://127.0.0.1:8090"
    assert p.normalize_url("http://localhost/d") == "http://localhost/d"
    for bad in ("http://example.com/d", "ftp://example.com", "example.com", "https://user:pw@example.com/d",
                "http://127.0.0.1.evil.example/d"):
        with pytest.raises(p.ProtocolError):
            p.normalize_url(bad)


def test_body_round_trip_and_compression():
    small, enc = p.encode_body({"v": 1})
    assert enc == "identity" and p.decode_body(small, enc) == {"v": 1}
    payload = {"v": 1, "text": "x" * 5000, "uni": "Zoryx ü"}
    packed, enc = p.encode_body(payload)
    assert enc == "gzip" and len(packed) < 600 and p.decode_body(packed, enc) == payload
    assert p.encode_body(payload, compress=False)[1] == "identity"


def test_policy_defaults_keep_dangerous_capabilities_off():
    policy = Policy(DashboardSettings())
    for name in ("files.write", "config", "marketplace", "commands.owner", "backups.restore", "guilds.leave", "system"):
        assert not policy.allows(name), name
        assert policy.needs_approval(name), name
    for name in ("view", "logs", "chat.read", "extensions"):
        assert policy.allows(name), name
    assert {c["name"] for c in policy.describe()} == set(NAMES)


def test_lock_leaves_only_reading():
    policy = Policy(DashboardSettings(locked=True, capabilities=["view", "logs", "extensions", "chat.send", "files.read"]))
    assert policy.allows("view") and policy.allows("logs") and policy.allows("files.read")
    assert not policy.allows("extensions") and not policy.allows("chat.send")


def test_config_rejects_unknown_capabilities_and_unsafe_roots():
    assert Settings.model_validate({}).modules.dashboard is False
    with pytest.raises(ValueError):
        DashboardSettings(capabilities=["view", "root"])
    for root in ("/etc", "../outside", "extensions/../..", ""):
        with pytest.raises(ValueError):
            DashboardSettings(file_roots=[root])
    settings, _ = Config.parse(Config.default_template())
    assert settings.dashboard.file_roots == ["extensions"] and not settings.dashboard.locked
    with pytest.raises(ConfigError):
        Config.parse('[dashboard]\ncapabilities = ["everything"]\n')


async def test_large_responses_are_read_completely():
    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    from zdbf.cogs.dashboard import client

    body = bytes(range(256)) * 12000

    async def big(request):
        response = web.StreamResponse()
        await response.prepare(request)
        for i in range(0, len(body), 50000):
            await response.write(body[i:i + 50000])
        return response

    app = web.Application()
    app.router.add_get("/big", big)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        async with session.get(server.make_url("/big")) as resp:
            assert await client._read(resp) == body
        limit = client.MAX_RESPONSE
        client.MAX_RESPONSE = 100000
        try:
            async with session.get(server.make_url("/big")) as resp:
                with pytest.raises(client.LinkError):
                    await client._read(resp)
        finally:
            client.MAX_RESPONSE = limit
