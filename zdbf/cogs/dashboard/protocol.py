# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import gzip
import hashlib
import hmac
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

__all__ = [
    "CODE_LENGTH",
    "MAX_COMMAND_AGE",
    "MAX_SKEW",
    "PAIR_PATH",
    "PULL_PATH",
    "PUSH_PATH",
    "VERSION",
    "ProtocolError",
    "code_id",
    "decode_body",
    "derive_secret",
    "encode_body",
    "normalize_code",
    "normalize_url",
    "pair_ack",
    "pair_proof",
    "request_signature",
    "response_signature",
]

VERSION = 1
MAX_SKEW = 60
MAX_COMMAND_AGE = 120
CODE_LENGTH = 32
PAIR_PATH = "api/bot/pair.php"
PULL_PATH = "api/bot/pull.php"
PUSH_PATH = "api/bot/push.php"
GZIP_MIN = 512
_CODE_RE = re.compile(r"^[A-Z2-7]{32}$")
_HEX_RE = re.compile(r"^[0-9a-f]+$")


class ProtocolError(ValueError):
    pass


def normalize_code(code: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", code or "").upper()
    if not _CODE_RE.match(cleaned):
        raise ProtocolError("That is not a pairing code. Copy all 32 characters from the setup page.")
    return cleaned


def _mac(key: bytes, *parts: str) -> str:
    return hmac.new(key, "\n".join(parts).encode(), hashlib.sha256).hexdigest()


def code_id(code: str) -> str:
    return hashlib.sha256(b"zdbf-pair-id\n" + code.encode()).hexdigest()[:32]


def pair_proof(code: str, bot_nonce: str, bot_id: str) -> str:
    return _mac(code.encode(), "zdbf-pair-proof", bot_nonce, bot_id)


def pair_ack(code: str, bot_nonce: str, server_nonce: str, install_id: str) -> str:
    return _mac(code.encode(), "zdbf-pair-ack", bot_nonce, server_nonce, install_id)


def derive_secret(code: str, bot_nonce: str, server_nonce: str, install_id: str) -> str:
    return _mac(code.encode(), "zdbf-dashboard-secret-v1", bot_nonce, server_nonce, install_id)


def _key(secret: str) -> bytes:
    if len(secret) != 64 or not _HEX_RE.match(secret):
        raise ProtocolError("invalid link secret")
    return bytes.fromhex(secret)


def request_signature(secret: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    return _mac(_key(secret), "POST", path, timestamp, nonce, hashlib.sha256(body).hexdigest())


def response_signature(secret: str, path: str, nonce: str, timestamp: str, body: bytes) -> str:
    return _mac(_key(secret), "RESP", path, nonce, timestamp, hashlib.sha256(body).hexdigest())


def encode_body(payload: dict[str, Any], *, compress: bool = True) -> tuple[bytes, str]:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    if compress and len(raw) >= GZIP_MIN:
        return gzip.compress(raw, 6), "gzip"
    return raw, "identity"


def decode_body(raw: bytes, encoding: str) -> dict[str, Any]:
    if encoding == "gzip":
        raw = gzip.decompress(raw)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ProtocolError("unexpected payload")
    return data


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def normalize_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ProtocolError("Enter the full address of the dashboard, for example https://example.com/dashboard")
    if parts.username or parts.password:
        raise ProtocolError("The address must not contain a user name or password.")
    if parts.scheme == "http" and not _is_loopback(parts.hostname):
        raise ProtocolError("The dashboard must use HTTPS. Plain HTTP is only accepted for 127.0.0.1 and localhost.")
    path = re.sub(r"/+", "/", parts.path)
    path = re.sub(r"/(index|setup|login)\.php$", "", path).rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
