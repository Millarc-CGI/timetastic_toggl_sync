"""
Timezone-aware date range helpers for Toggl/Timetastic queries.

Returns UTC ISO 8601 strings suitable for API calls, based on local
calendar ranges using the configured TIMEZONE.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, time
from typing import Tuple

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore


def _localize(dt: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def day_bounds_local(d: date, tz_name: str) -> Tuple[datetime, datetime]:
    """Return start/end datetimes for the given local day in tz."""
    start_local = _localize(datetime.combine(d, time(0, 0, 0)), tz_name)
    end_local = _localize(datetime.combine(d, time(23, 59, 59)), tz_name)
    return start_local, end_local


def last_week_range(tz_name: str) -> Tuple[str, str]:
    """Return last week (Mon..Sun) as UTC ISO strings."""
    today = date.today()
    days_since_monday = today.weekday()
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)

    start_local, _ = day_bounds_local(last_monday, tz_name)
    _, end_local = day_bounds_local(last_sunday, tz_name)
    return _to_utc_iso(start_local), _to_utc_iso(end_local)


def last_month_range(tz_name: str) -> Tuple[str, str]:
    """Return last month (1st..last) as UTC ISO strings."""
    today = date.today()
    first_of_current = today.replace(day=1)
    last_of_last = first_of_current - timedelta(days=1)
    first_of_last = last_of_last.replace(day=1)

    start_local, _ = day_bounds_local(first_of_last, tz_name)
    _, end_local = day_bounds_local(last_of_last, tz_name)
    return _to_utc_iso(start_local), _to_utc_iso(end_local)


def current_week_range(tz_name: str) -> Tuple[str, str]:
    """Return current week (Mon..today) as UTC ISO strings."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    start_local, _ = day_bounds_local(monday, tz_name)
    _, end_local = day_bounds_local(today, tz_name)
    return _to_utc_iso(start_local), _to_utc_iso(end_local)


def current_month_to_date_range(tz_name: str) -> Tuple[str, str]:
    """Return 1st of current month..today as UTC ISO strings."""
    today = date.today()
    first = today.replace(day=1)
    start_local, _ = day_bounds_local(first, tz_name)
    _, end_local = day_bounds_local(today, tz_name)
    return _to_utc_iso(start_local), _to_utc_iso(end_local)

