"""Cron (5-field) and RRULE scheduling for ``trigger.cron`` (croniter is not a dependency).

Cron fields: minute hour day-of-month month day-of-week, each supporting ``*``, lists (``1,15``), ranges (``1-5``),
steps (``*/15``, ``10-50/10``, ``5/15``), month/day names (``jan``, ``mon``) and day-of-week ``7`` = Sunday. When both
day-of-month and day-of-week are restricted a time matches if EITHER matches (Vixie cron semantics). Aliases:
``@hourly @daily @midnight @weekly @monthly @yearly @annually``. Times are evaluated as wall-clock in the trigger's
timezone (IANA name), so "0 9 * * 1" fires at 09:00 local across DST changes.

RRULE strings (RFC 5545, e.g. ``FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0``) are evaluated with ``dateutil.rrule``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr


class CronError(ValueError):
    pass


ALIASES = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0",
           "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *"}
MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
DAYS = {d: i for i, d in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_NAMES: tuple[dict[str, int] | None, ...] = (None, None, None, MONTHS, DAYS)
FIELD_NAMES = ("minute", "hour", "day-of-month", "month", "day-of-week")
MAX_SEARCH_DAYS = 366 * 5


@dataclass(frozen=True)
class CronSpec:
    minutes: frozenset[int]
    hours: frozenset[int]
    doms: frozenset[int]
    months: frozenset[int]
    dows: frozenset[int]          # 0 = Sunday … 6 = Saturday
    dom_star: bool
    dow_star: bool
    source: str

    def day_matches(self, dt: datetime) -> bool:
        dow = (dt.weekday() + 1) % 7   # Python Monday=0 → cron Sunday=0
        dom_ok, dow_ok = dt.day in self.doms, dow in self.dows
        if self.dom_star and self.dow_star:
            return True
        if self.dom_star:
            return dow_ok
        if self.dow_star:
            return dom_ok
        return dom_ok or dow_ok

    def matches(self, dt: datetime) -> bool:
        return (dt.minute in self.minutes and dt.hour in self.hours and dt.month in self.months
                and self.day_matches(dt))


def _value(tok: str, idx: int) -> int:
    names = _NAMES[idx]
    t = tok.strip().lower()
    if names and t in names:
        return names[t]
    if not t.isdigit():
        raise CronError(f"invalid {FIELD_NAMES[idx]} value {tok!r}")
    v = int(t)
    lo, hi = _BOUNDS[idx]
    if not lo <= v <= hi:
        raise CronError(f"{FIELD_NAMES[idx]} value {v} out of range {lo}-{hi}")
    return v


def _field(expr: str, idx: int) -> tuple[frozenset[int], bool]:
    lo, hi = _BOUNDS[idx]
    out: set[int] = set()
    star = False
    if not expr:
        raise CronError(f"empty {FIELD_NAMES[idx]} field")
    for part in expr.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            if not step_s.isdigit() or int(step_s) < 1:
                raise CronError(f"invalid step in {FIELD_NAMES[idx]}: {step_s!r}")
            step = int(step_s)
        if part in ("*", "?"):
            a, b = lo, hi
            star = star or step == 1
        elif "-" in part:
            a_s, b_s = part.split("-", 1)
            a, b = _value(a_s, idx), _value(b_s, idx)
            if a > b:
                raise CronError(f"invalid range {part!r} in {FIELD_NAMES[idx]}")
        else:
            a = _value(part, idx)
            b = hi if step > 1 else a        # "5/15" → from 5 to max every 15
        out.update(range(a, b + 1, step))
    if idx == 4:
        if 7 in out:
            out.discard(7)
            out.add(0)
        if star:
            out = set(range(0, 7))
    return frozenset(out), star


def parse_cron(expr: str) -> CronSpec:
    if not isinstance(expr, str) or not expr.strip():
        raise CronError("cron expression is empty")
    src = " ".join(expr.split())
    fields = ALIASES.get(src.lower(), src).split(" ")
    if len(fields) != 5:
        raise CronError("cron expression must have 5 fields: minute hour day-of-month month day-of-week")
    parsed = [_field(f, i) for i, f in enumerate(fields)]
    return CronSpec(minutes=parsed[0][0], hours=parsed[1][0], doms=parsed[2][0], months=parsed[3][0],
                    dows=parsed[4][0], dom_star=parsed[2][1], dow_star=parsed[4][1], source=src)


def get_tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise CronError(f"unknown timezone {name!r}") from e


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def next_cron(expr: str | CronSpec, after: datetime, tz: str | None = "UTC") -> datetime:
    """First fire time strictly after ``after`` (UTC-aware result)."""
    spec = expr if isinstance(expr, CronSpec) else parse_cron(expr)
    zone = get_tz(tz)
    after_utc = _aware(after).astimezone(UTC)
    t = after_utc.astimezone(zone).replace(tzinfo=None, second=0, microsecond=0) + timedelta(minutes=1)
    limit = t + timedelta(days=MAX_SEARCH_DAYS)
    while t <= limit:
        if t.month not in spec.months:
            t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            continue
        if not spec.day_matches(t):
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t.hour not in spec.hours:
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if t.minute not in spec.minutes:
            later = [m for m in spec.minutes if m > t.minute]
            t = t.replace(minute=min(later)) if later else (t + timedelta(hours=1)).replace(minute=0)
            continue
        candidate = t.replace(tzinfo=zone).astimezone(UTC)
        if candidate > after_utc:
            return candidate
        t += timedelta(minutes=1)
    raise CronError(f"cron expression {spec.source!r} never fires")


def next_rrule(rule: str, after: datetime, tz: str | None = "UTC", dtstart: datetime | None = None) -> datetime | None:
    zone = get_tz(tz)
    after_local = _aware(after).astimezone(zone)
    start = (_aware(dtstart).astimezone(zone) if dtstart else after_local.replace(second=0, microsecond=0))
    try:
        rr = rrulestr(rule.strip(), dtstart=start)
    except (ValueError, TypeError) as e:
        raise CronError(f"invalid rrule: {e}") from e
    nxt = rr.after(after_local, inc=False)  # type: ignore[union-attr]
    return nxt.astimezone(UTC) if nxt else None


def validate_schedule(config: dict[str, Any]) -> str | None:
    """None when the trigger.cron config is usable, else a readable error."""
    try:
        get_tz(config.get("timezone"))
        if config.get("cron"):
            parse_cron(str(config["cron"]))
        elif config.get("rrule"):
            next_rrule(str(config["rrule"]), datetime.now(UTC), config.get("timezone"))
        else:
            return "either cron or rrule is required"
    except CronError as e:
        return str(e)
    return None


def next_run_at(config: dict[str, Any], after: datetime, default_tz: str | None = None) -> datetime | None:
    tz = config.get("timezone") or default_tz or "UTC"
    if config.get("cron"):
        return next_cron(str(config["cron"]), after, tz)
    if config.get("rrule"):
        return next_rrule(str(config["rrule"]), after, tz)
    return None


_DOW_LABEL = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


def describe(config: dict[str, Any], default_tz: str | None = None) -> str:
    """Human summary for ``automation_workflows.trigger_summary``."""
    tz = config.get("timezone") or default_tz or "UTC"
    if config.get("rrule"):
        return f"Recurring ({config['rrule']}) {tz}"
    try:
        spec = parse_cron(str(config.get("cron") or ""))
    except CronError:
        return f"Cron {config.get('cron')} {tz}"
    one_time = len(spec.minutes) == 1 and len(spec.hours) == 1
    at = f"{min(spec.hours):02d}:{min(spec.minutes):02d}" if one_time else None
    if at and spec.dom_star and len(spec.months) == 12:
        if spec.dow_star:
            return f"Every day at {at} ({tz})"
        days = ", ".join(_DOW_LABEL[d] for d in sorted(spec.dows))
        return f"Every {days} at {at} ({tz})"
    if at and not spec.dom_star and spec.dow_star and len(spec.months) == 12 and len(spec.doms) == 1:
        return f"Monthly on day {min(spec.doms)} at {at} ({tz})"
    return f"Cron {spec.source} ({tz})"
