# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import ast
import contextlib
import datetime as dt
import ipaddress
import json
import operator
import random
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import discord

__all__ = [
    "CONDITION_HELP",
    "VARIABLE_HELP",
    "Automation",
    "check_conditions",
    "check_url",
    "render",
    "rule_types",
    "safe_math",
    "validate_conditions",
]

CONDITION_HELP = """\
Conditions are a JSON list. All must match (or any, with `{"logic": "or", "rules": [...]}`).
```json
[
  {"type": "has_role", "role_id": 123},
  {"type": "lacks_role", "role_id": 456},
  {"type": "channel", "ids": [789]},
  {"type": "time_range", "start": "09:00", "end": "22:00"},
  {"type": "day_of_week", "days": ["mon", "fri"]},
  {"type": "account_age", "min_days": 7},
  {"type": "member_age", "min_days": 1},
  {"type": "chance", "percent": 50},
  {"type": "not_bot"},
  {"type": "role_above", "role_id": 123},
  {"type": "role_below", "role_id": 123},
  {"type": "message_count", "operator": ">=", "value": 50},
  {"type": "variable", "name": "content", "operator": "contains", "value": "help"}
]
```
-# `message_count` counts a member's messages in this server from the moment the first automation with that \
rule exists. `variable` compares any template variable; operators: == != contains startswith > < >= <=."""

VARIABLE_HELP = (
    "`{user}` `{username}` `{display_name}` `{user_id}` `{server}` `{member_count}` `{channel}` `{channel_name}` "
    "`{content}` `{emoji}` `{voice_channel}` `{date}` `{time}` `{timestamp}` `{random:1-100}` `{math:2*(3+4)}`"
)
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CONDITION_TYPES = {"has_role", "lacks_role", "channel", "not_channel", "time_range", "day_of_week",
                    "account_age", "member_age", "chance", "not_bot", "content_contains", "role_above",
                    "role_below", "message_count", "variable"}
_OPERATORS = ("==", "!=", "contains", "startswith", ">", "<", ">=", "<=")


@dataclass
class Automation:
    hook_id: str
    guild_id: int
    name: str
    template: str
    config: dict[str, Any]
    conditions: dict[str, Any] = field(default_factory=lambda: {"logic": "and", "rules": []})
    enabled: bool = True
    created_by: int = 0
    created_at: str = ""
    updated_at: str = ""
    run_count: int = 0
    error_count: int = 0
    last_run: str | None = None
    last_error: str | None = None
    consecutive_errors: int = 0

    @classmethod
    def from_row(cls, row: Any) -> Automation:
        conditions = json.loads(row["conditions"] or "[]")
        if isinstance(conditions, list):
            conditions = {"logic": "and", "rules": conditions}
        return cls(
            hook_id=row["hook_id"], guild_id=row["guild_id"], name=row["name"], template=row["template"],
            config=json.loads(row["config"] or "{}"), conditions=conditions, enabled=bool(row["enabled"]),
            created_by=row["created_by"], created_at=row["created_at"], updated_at=row["updated_at"],
            run_count=row["run_count"], error_count=row["error_count"], last_run=row["last_run"],
            last_error=row["last_error"],
        )


def validate_conditions(raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else []
        except json.JSONDecodeError as exc:
            return None, f"invalid JSON: {exc.msg} (line {exc.lineno})"
    if isinstance(raw, list):
        raw = {"logic": "and", "rules": raw}
    if not isinstance(raw, dict) or not isinstance(raw.get("rules", []), list):
        return None, "expected a list of rules"
    logic = str(raw.get("logic", "and")).lower()
    if logic not in ("and", "or"):
        return None, "logic must be 'and' or 'or'"
    for i, rule in enumerate(raw.get("rules", []), 1):
        if not isinstance(rule, dict) or rule.get("type") not in _CONDITION_TYPES:
            return None, f"rule {i}: unknown type {rule.get('type') if isinstance(rule, dict) else rule!r}"
        if rule["type"] == "time_range":
            for key in ("start", "end"):
                if not re.fullmatch(r"\d{1,2}:\d{2}", str(rule.get(key, ""))):
                    return None, f"rule {i}: {key} must look like HH:MM"
        if rule["type"] in ("message_count", "variable") and str(rule.get("operator", "==")) not in _OPERATORS:
            return None, f"rule {i}: operator must be one of {', '.join(_OPERATORS)}"
        if rule["type"] == "message_count" and not str(rule.get("value", "")).lstrip("-").isdigit():
            return None, f"rule {i}: value must be a whole number"
        if rule["type"] == "variable" and not rule.get("name"):
            return None, f"rule {i}: name is required"
        if rule["type"] in ("role_above", "role_below") and not str(rule.get("role_id", "")).isdigit():
            return None, f"rule {i}: role_id must be a role ID"
    return {"logic": logic, "rules": raw.get("rules", [])[:20]}, None


def compare(actual: Any, op: str, expected: Any) -> bool:
    try:
        a, b = float(actual), float(expected)
    except (TypeError, ValueError):
        a, b = str(actual if actual is not None else "").lower(), str(expected).lower()
    match op:
        case "==":
            return a == b
        case "!=":
            return a != b
        case "contains":
            return str(expected).lower() in str(actual if actual is not None else "").lower()
        case "startswith":
            return str(actual if actual is not None else "").lower().startswith(str(expected).lower())
    try:
        return {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le}[op](a, b)
    except (KeyError, TypeError):
        return False


def _role_position(member: discord.Member | None, role_id: Any) -> tuple[int, int] | None:
    if not isinstance(member, discord.Member):
        return None
    try:
        role = member.guild.get_role(int(role_id))
    except (TypeError, ValueError):
        return None
    return None if role is None else (member.top_role.position, role.position)


def _rule(rule: dict[str, Any], member: discord.Member | None, channel_id: int | None,
          content: str | None, now: dt.datetime, context: dict[str, Any]) -> bool:
    kind = rule.get("type")
    role_ids = {r.id for r in member.roles} if isinstance(member, discord.Member) else set()
    match kind:
        case "has_role":
            return int(rule.get("role_id", 0)) in role_ids
        case "lacks_role":
            return int(rule.get("role_id", 0)) not in role_ids
        case "channel":
            return channel_id in {int(x) for x in rule.get("ids", [])}
        case "not_channel":
            return channel_id not in {int(x) for x in rule.get("ids", [])}
        case "time_range":
            start = dt.time.fromisoformat(str(rule["start"]).zfill(5))
            end = dt.time.fromisoformat(str(rule["end"]).zfill(5))
            t = now.time()
            return start <= t <= end if start <= end else t >= start or t <= end
        case "day_of_week":
            days = {str(d).lower()[:3] for d in rule.get("days", [])}
            return _DAYS[now.weekday()] in days
        case "account_age":
            return member is not None and (now - member.created_at).days >= int(rule.get("min_days", 0))
        case "member_age":
            joined = getattr(member, "joined_at", None)
            return joined is not None and (now - joined).days >= int(rule.get("min_days", 0))
        case "chance":
            return random.random() * 100 < float(rule.get("percent", 100))
        case "not_bot":
            return member is None or not member.bot
        case "content_contains":
            return content is not None and str(rule.get("text", "")).lower() in content.lower()
        case "role_above":
            pos = _role_position(member, rule.get("role_id"))
            return pos is not None and pos[0] > pos[1]
        case "role_below":
            pos = _role_position(member, rule.get("role_id"))
            return pos is not None and pos[0] < pos[1]
        case "message_count":
            return compare(context.get("message_count", 0), str(rule.get("operator", ">=")), rule.get("value", 0))
        case "variable":
            return compare(context.get(str(rule.get("name"))), str(rule.get("operator", "==")), rule.get("value", ""))
    return False


def rule_types(conditions: dict[str, Any]) -> set[str]:
    return {str(r.get("type")) for r in conditions.get("rules", []) if isinstance(r, dict)}


def check_conditions(conditions: dict[str, Any], *, member: discord.Member | None = None,
                     channel_id: int | None = None, content: str | None = None,
                     now: dt.datetime | None = None, context: dict[str, Any] | None = None) -> bool:
    rules = conditions.get("rules", [])
    if not rules:
        return True
    now = now or dt.datetime.now(dt.UTC)
    ctx = dict(context or {})
    if content is not None:
        ctx.setdefault("content", content)
    results = (_rule(r, member, channel_id, content, now, ctx) for r in rules)
    return any(results) if conditions.get("logic") == "or" else all(results)


_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_FUNCTION = re.compile(r"\{(random|math):([^{}]{1,200})\}")
_MATH_OPS: dict[type, Any] = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                              ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
_MATH_LIMIT = 1e15


def safe_math(expression: str) -> float | int:
    if len(expression) > 200:
        raise ValueError("expression too long")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError("invalid expression") from exc

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = ev(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in _MATH_OPS:
            try:
                result = _MATH_OPS[type(node.op)](ev(node.left), ev(node.right))
            except ZeroDivisionError as exc:
                raise ValueError("division by zero") from exc
            if abs(result) > _MATH_LIMIT:
                raise ValueError("result too large")
            return result
        raise ValueError("only numbers and + - * / // % are allowed")

    result = ev(tree)
    return int(result) if float(result).is_integer() else round(result, 6)


def _function(kind: str, arg: str) -> str | None:
    if kind == "random":
        m = re.fullmatch(r"\s*(-?\d{1,12})\s*-\s*(-?\d{1,12})\s*", arg)
        if not m:
            return None
        low, high = sorted((int(m[1]), int(m[2])))
        return str(random.randint(low, high))
    try:
        return str(safe_math(arg))
    except ValueError:
        return None


def render(template: str, **values: Any) -> str:
    now = dt.datetime.now(dt.UTC)
    builtins = {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"),
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S UTC"), "unix": int(now.timestamp())}
    merged = {**builtins, **values}
    text = _PLACEHOLDER.sub(lambda m: str(merged[m[1]]) if merged.get(m[1]) is not None else m[0], template)
    if "{" in text:
        text = _FUNCTION.sub(lambda m: _function(m[1], m[2]) or m[0], text)
    return text


def check_url(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "invalid URL"
    if parts.scheme != "https" or not parts.hostname:
        return "the URL must start with https://"
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return "local addresses are not allowed"
    with contextlib.suppress(ValueError):
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "private addresses are not allowed"
    return None


def member_values(member: discord.Member | discord.User, guild: discord.Guild | None) -> dict[str, Any]:
    return {
        "user": member.mention,
        "username": member.name,
        "display_name": member.display_name,
        "user_id": member.id,
        "guild_name": guild.name if guild else "",
        "server": guild.name if guild else "",
        "member_count": guild.member_count if guild else 0,
    }
