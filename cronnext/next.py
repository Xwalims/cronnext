"""Timezone aware occurrence search.

The wall clock arithmetic lives in :meth:`cronnext.expr.CronExpr.next_after`;
this module wraps it so that occurrences are expressed as timezone aware
datetimes and so that the two daylight saving problems are handled the way
a wall clock scheduler has to handle them.

Daylight saving rules
---------------------

*Non-existent local times* (the spring forward gap, e.g. ``02:30`` on a day
when the clock jumps from ``02:00`` to ``03:00``) never occur.  They are
skipped entirely: no timestamp is emitted for them and the search carries
on with the next local time that does exist.  The scheduled wall clock time
is never silently shifted, because a job that runs at 02:30 should not
quietly run at 04:30.

*Ambiguous local times* (the autumn fall back hour, where the same local
time happens twice) run exactly once, at ``fold=0``, which is the first of
the two passes through the clock.

A naive datetime passed to :func:`next_after` is interpreted as a wall clock
time in the requested zone.  An aware datetime is converted into that zone
first, so the expression always matches local time.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Set, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .expr import MAX_HORIZON_YEARS, CronExpr

__all__ = [
    "MAX_HORIZON_YEARS",
    "TimezoneError",
    "get_zone",
    "is_imaginary",
    "next_after",
    "to_utc",
]

_UTC = ZoneInfo("UTC")

#: Upper bound on candidate lookups per requested occurrence.  Each round
#: either emits an occurrence or skips a non-existent local time, and at
#: most a whole day's worth of them can fall in one gap, so this is ample.
_MAX_ATTEMPTS_PER_RESULT = 64


class TimezoneError(ValueError):
    """Raised when a timezone name cannot be resolved."""


def get_zone(name: Optional[str]) -> ZoneInfo:
    """Resolve an IANA timezone name.

    Args:
        name: Timezone name such as ``"Europe/Berlin"``, or None for UTC.

    Returns:
        The matching :class:`zoneinfo.ZoneInfo`.

    Raises:
        TimezoneError: If the name is unknown to the tz database.
    """
    if name is None:
        return _UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise TimezoneError(f"unknown timezone {name!r}") from error


def is_imaginary(moment: datetime) -> bool:
    """Return True when ``moment`` names a spring-forward DST gap.

    The test is the standard round trip: convert the local time to UTC and
    back.  A wall clock time inside the gap does not survive the round
    trip, because ``zoneinfo`` maps it onto the post-transition offset and
    the local time that comes back is later than the one that went in.

    Args:
        moment: An aware datetime whose tzinfo is the zone under test.

    Returns:
        True when the wall clock time named by ``moment`` does not exist.

    Raises:
        ValueError: If ``moment`` is naive.
    """
    if moment.tzinfo is None:
        raise ValueError("is_imaginary requires an aware datetime")
    return moment.astimezone(_UTC).astimezone(moment.tzinfo).replace(
        fold=0
    ) != moment.replace(fold=0)


def to_utc(moment: datetime) -> datetime:
    """Return ``moment`` converted to UTC, assuming UTC when naive.

    Args:
        moment: A naive or aware datetime.

    Returns:
        The same instant expressed in UTC.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=_UTC)
    return moment.astimezone(_UTC)


def next_after(
    expression: Union[str, CronExpr],
    after: datetime,
    count: int = 1,
    tz: Optional[str] = None,
    horizon_years: int = MAX_HORIZON_YEARS,
) -> List[datetime]:
    """Return up to ``count`` occurrences strictly after ``after``.

    Args:
        expression: A crontab expression or an already parsed
            :class:`~cronnext.expr.CronExpr`.
        after: Naive datetime, interpreted as local time in ``tz``, or an
            aware datetime, which is converted into ``tz`` first.
        count: Maximum number of occurrences; 0 returns an empty list.
        tz: IANA timezone name, or None for UTC.
        horizon_years: How far past the local year of ``after`` to search.

    Returns:
        A list of aware datetimes in ``tz``, strictly increasing both as
        local wall clock times and as absolute instants.  Local times
        inside a spring-forward gap are skipped rather than shifted, and
        ambiguous local times appear once, at ``fold=0``.  The list may be
        shorter than ``count`` when the expression cannot fire within the
        horizon.

    Raises:
        ValueError: If ``count`` is negative.
        TimezoneError: If ``tz`` is not a known timezone.
        TypeError: If ``expression`` is neither a string nor a CronExpr.
    """
    if isinstance(expression, str):
        expr = CronExpr.parse(expression)
    elif isinstance(expression, CronExpr):
        expr = expression
    else:
        raise TypeError("expression must be a string or a CronExpr")
    if count < 0:
        raise ValueError("count must not be negative")
    if count == 0:
        return []

    zone = get_zone(tz)
    if after.tzinfo is None:
        local_start = after.replace(microsecond=0)
    else:
        local_start = after.astimezone(zone).replace(tzinfo=None, microsecond=0)

    # The horizon is fixed once, against the caller's start, so that every
    # resumed search in the loop below is bound by the same deadline rather
    # than sliding forward by another horizon each time.
    last_year = local_start.year + horizon_years

    step = expr.resolution
    cursor = local_start
    results: List[datetime] = []
    seen: Set[datetime] = set()
    attempts = 0
    limit = count * _MAX_ATTEMPTS_PER_RESULT
    # The cursor only ever moves forward and every iteration either emits a
    # result or spends an attempt, so the loop is guaranteed to terminate.
    while len(results) < count and attempts <= limit:
        found = expr.next_after(cursor, 1, horizon_years=last_year - cursor.year)
        if not found:
            break
        candidate_naive = found[0]
        cursor = candidate_naive + step
        attempts += 1

        local = candidate_naive.replace(tzinfo=zone, fold=0)
        if is_imaginary(local):
            # This wall clock time does not exist; skip it entirely.
            continue
        instant = local.astimezone(_UTC)
        if instant in seen:
            continue
        seen.add(instant)
        results.append(local)
    return results
