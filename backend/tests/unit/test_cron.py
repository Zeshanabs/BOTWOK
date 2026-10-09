"""Cron (5-field) + RRULE scheduling for trigger.cron (croniter is not a dependency)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.workflows.cron import (
    CronError,
    describe,
    next_cron,
    next_rrule,
    next_run_at,
    parse_cron,
    validate_schedule,
)

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)   # a Thursday


def test_parse_fields():
    s = parse_cron("*/15 9-17 1,15 jan-mar mon-fri")
    assert s.minutes == {0, 15, 30, 45}
    assert s.hours == set(range(9, 18))
    assert s.doms == {1, 15} and s.months == {1, 2, 3} and s.dows == {1, 2, 3, 4, 5}
    assert not s.dom_star and not s.dow_star
    assert parse_cron("0 0 * * 7").dows == {0}           # 7 == Sunday
    assert parse_cron("5/20 * * * *").minutes == {5, 25, 45}
    assert parse_cron("10-50/20 * * * *").minutes == {10, 30, 50}
    assert parse_cron("@weekly").source == "@weekly"


@pytest.mark.parametrize("bad", ["", "* * * *", "* * * * * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *",
                                 "* * * * 8", "5-1 * * * *", "*/0 * * * *", "x * * * *", "1,,2 * * * *"])
def test_invalid(bad):
    with pytest.raises(CronError):
        parse_cron(bad)


def test_next_weekly_in_timezone():
    # Monday 2026-10-12 09:00 Europe/Paris (CEST, UTC+2) = 07:00 UTC
    assert next_cron("0 9 * * 1", T0, "Europe/Paris") == datetime(2026, 10, 12, 7, 0, tzinfo=UTC)
    # after the DST change (Oct 25) the same wall time is 08:00 UTC
    assert next_cron("0 9 * * 1", datetime(2026, 10, 27, tzinfo=UTC), "Europe/Paris") == datetime(2026, 11, 2, 8, 0, tzinfo=UTC)


def test_next_basic_cases():
    assert next_cron("*/15 * * * *", T0) == datetime(2026, 10, 8, 12, 15, tzinfo=UTC)
    assert next_cron("* * * * *", datetime(2026, 10, 8, 12, 0, 30, tzinfo=UTC)) == datetime(2026, 10, 8, 12, 1, tzinfo=UTC)
    assert next_cron("0 0 1 * *", T0) == datetime(2026, 11, 1, tzinfo=UTC)
    assert next_cron("0 0 29 2 *", T0) == datetime(2028, 2, 29, tzinfo=UTC)
    assert next_cron("30 23 31 12 *", T0) == datetime(2026, 12, 31, 23, 30, tzinfo=UTC)
    # strictly after: a time exactly on a slot moves to the next one
    assert next_cron("0 12 * * *", T0) == datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def test_dom_dow_or_semantics():
    # "on the 13th OR on Fridays": from Thu Oct 8 → Fri Oct 9
    assert next_cron("0 0 13 * 5", T0) == datetime(2026, 10, 9, tzinfo=UTC)
    # dom restricted, dow '*' → only the 13th
    assert next_cron("0 0 13 * *", T0) == datetime(2026, 10, 13, tzinfo=UTC)


def test_rrule_and_dispatch_config():
    nxt = next_rrule("FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0;BYSECOND=0", T0, "America/New_York")
    assert nxt == datetime(2026, 10, 12, 13, 0, tzinfo=UTC)
    assert next_run_at({"cron": "0 9 * * 1"}, T0, "Europe/Paris") == datetime(2026, 10, 12, 7, 0, tzinfo=UTC)
    assert next_run_at({"cron": "0 9 * * 1", "timezone": "UTC"}, T0, "Europe/Paris") == datetime(2026, 10, 12, 9, tzinfo=UTC)
    assert next_run_at({}, T0) is None
    assert validate_schedule({"cron": "0 9 * * 1"}) is None
    assert validate_schedule({"cron": "0 9 * * 1", "timezone": "Mars/Base"}) is not None
    assert validate_schedule({"rrule": "FREQ=NOPE"}) is not None
    assert validate_schedule({}) == "either cron or rrule is required"


def test_describe():
    assert describe({"cron": "0 9 * * 1", "timezone": "Europe/Paris"}) == "Every Monday at 09:00 (Europe/Paris)"
    assert describe({"cron": "@daily"}) == "Every day at 00:00 (UTC)"
    assert describe({"cron": "0 9 1 * *"}, "Europe/Paris") == "Monthly on day 1 at 09:00 (Europe/Paris)"
    assert describe({"cron": "*/5 * * * *"}).startswith("Cron */5")
