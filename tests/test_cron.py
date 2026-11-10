# SPDX-License-Identifier: Apache-2.0
import datetime as dt

import pytest

from zdbf.core.cron import CronError, CronExpression

UTC = dt.UTC


def at(*args):
    return dt.datetime(*args, tzinfo=UTC)


def test_every_minute():
    e = CronExpression.parse("* * * * *")
    assert e.next_after(at(2026, 1, 1, 10, 0, 30)) == at(2026, 1, 1, 10, 1)


def test_daily_macro_and_weekday_names():
    assert CronExpression.parse("@daily").next_after(at(2026, 1, 1, 10, 0)) == at(2026, 1, 2, 0, 0)
    e = CronExpression.parse("30 9 * * mon-fri")
    assert e.next_after(at(2026, 1, 3, 12, 0)) == at(2026, 1, 5, 9, 30)


def test_sunday_is_zero_and_seven():
    for expr in ("0 12 * * 0", "0 12 * * 7", "0 12 * * sun"):
        assert CronExpression.parse(expr).next_after(at(2026, 1, 1, 0, 0)) == at(2026, 1, 4, 12, 0)


def test_steps_ranges_and_lists():
    e = CronExpression.parse("0-30/15 1,13 * * *")
    assert e.minutes == {0, 15, 30}
    assert e.hours == {1, 13}


def test_dom_or_dow_semantics():
    e = CronExpression.parse("0 0 15 * fri")
    runs = e.upcoming(at(2026, 1, 1), 3)
    assert runs == [at(2026, 1, 2), at(2026, 1, 9), at(2026, 1, 15)]


def test_month_skip_and_leap_day():
    e = CronExpression.parse("0 0 29 2 *")
    assert e.next_after(at(2026, 3, 1)) == at(2028, 2, 29)


@pytest.mark.parametrize("bad", ["* * * *", "60 * * * *", "* 24 * * *", "5-1 * * * *", "*/0 * * * *", "x * * * *"])
def test_invalid(bad):
    with pytest.raises(CronError):
        CronExpression.parse(bad)
    assert CronExpression.validate(bad)


def test_describe():
    assert CronExpression.parse("*/5 * * * *").describe() == "Every 5 minutes"
    assert CronExpression.parse("0 9 * * *").describe() == "Every day at 09:00"
    assert "Monday" in CronExpression.parse("0 9 * * 1").describe()
