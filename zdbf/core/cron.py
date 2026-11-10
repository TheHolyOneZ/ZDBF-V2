# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

__all__ = ["CronError", "CronExpression"]

MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                      "nov", "dec"), 1)}
DAYS = {d: i for i, d in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
FIELDS = (("minute", 0, 59, {}), ("hour", 0, 23, {}), ("day", 1, 31, {}), ("month", 1, 12, MONTHS),
          ("weekday", 0, 7, DAYS))
DAY_NAMES = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


class CronError(ValueError):
    pass


def _value(token: str, lo: int, hi: int, names: dict[str, int], field: str) -> int:
    token = token.strip().lower()
    if token in names:
        return names[token]
    if not token.isdigit():
        raise CronError(f"{field}: '{token}' is not a number")
    v = int(token)
    if not lo <= v <= hi:
        raise CronError(f"{field}: {v} is outside {lo}-{hi}")
    return v


def _parse_field(text: str, field: str, lo: int, hi: int, names: dict[str, int]) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"{field}: empty list item")
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"{field}: invalid step '/{step_text}'")
            step = int(step_text)
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = _value(a, lo, hi, names, field), _value(b, lo, hi, names, field)
            if start > end:
                raise CronError(f"{field}: range {start}-{end} is reversed")
        else:
            start = _value(part, lo, hi, names, field)
            end = hi if step > 1 else start
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True)
class CronExpression:
    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    day_restricted: bool
    weekday_restricted: bool

    @classmethod
    def parse(cls, expression: str) -> CronExpression:
        text = MACROS.get(expression.strip().lower(), expression.strip())
        parts = text.split()
        if len(parts) != 5:
            raise CronError(f"expected 5 fields (minute hour day month weekday), got {len(parts)}")
        sets = [_parse_field(p, *spec[:3], spec[3]) for p, spec in zip(parts, FIELDS, strict=True)]
        weekdays = frozenset(0 if d == 7 else d for d in sets[4])
        return cls(expression.strip(), sets[0], sets[1], sets[2], sets[3], weekdays,
                   parts[2] != "*", parts[4] != "*")

    @staticmethod
    def validate(expression: str) -> str | None:
        try:
            CronExpression.parse(expression)
        except CronError as exc:
            return str(exc)
        return None

    def _day_matches(self, when: dt.datetime) -> bool:
        dom = when.day in self.days
        dow = ((when.weekday() + 1) % 7) in self.weekdays
        if self.day_restricted and self.weekday_restricted:
            return dom or dow
        return dom and dow

    def matches(self, when: dt.datetime) -> bool:
        return (when.minute in self.minutes and when.hour in self.hours and when.month in self.months
                and self._day_matches(when))

    def next_after(self, after: dt.datetime, *, horizon_days: int = 1500) -> dt.datetime | None:
        cur = after.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        limit = after + dt.timedelta(days=horizon_days)
        while cur <= limit:
            if cur.month not in self.months:
                year, month = (cur.year + 1, 1) if cur.month == 12 else (cur.year, cur.month + 1)
                cur = cur.replace(year=year, month=month, day=1, hour=0, minute=0)
                continue
            if not self._day_matches(cur):
                cur = (cur + dt.timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if cur.hour not in self.hours:
                cur = (cur + dt.timedelta(hours=1)).replace(minute=0)
                continue
            if cur.minute not in self.minutes:
                cur += dt.timedelta(minutes=1)
                continue
            return cur
        return None

    def upcoming(self, after: dt.datetime, count: int = 5) -> list[dt.datetime]:
        out: list[dt.datetime] = []
        cur = after
        while len(out) < count and (nxt := self.next_after(cur)) is not None:
            out.append(nxt)
            cur = nxt
        return out

    def describe(self) -> str:
        parts = MACROS.get(self.expression.lower(), self.expression).split()
        minute, hour, day, month, weekday = parts
        at = f"{hour.zfill(2)}:{minute.zfill(2)}" if hour.isdigit() and minute.isdigit() else None
        if parts == ["*"] * 5:
            return "Every minute"
        if minute.startswith("*/") and hour == day == month == weekday == "*":
            return f"Every {minute[2:]} minutes"
        if minute.isdigit() and hour == "*" and day == month == weekday == "*":
            return f"Every hour at minute {minute}"
        if minute.isdigit() and hour.startswith("*/") and day == month == weekday == "*":
            return f"Every {hour[2:]} hours at minute {minute}"
        if at and day == month == weekday == "*":
            return f"Every day at {at}"
        if at and day == month == "*" and weekday not in ("*",):
            names = ", ".join(DAY_NAMES[d] for d in sorted(self.weekdays))
            return f"Every {names} at {at}"
        if at and day.isdigit() and month == weekday == "*":
            return f"Day {day} of every month at {at}"
        return f"Cron `{self.expression}`"
