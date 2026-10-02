"""A deliberately naive reference implementation.

This module exists only so the test suite can prove that the smart-skip
search in :mod:`cronnext.expr` returns exactly what a dumb minute-by-minute
scan returns.  It is not part of the public API and is never imported by
the library itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Union

from cronnext.expr import MAX_HORIZON_YEARS, CronExpr

__all__ = ["naive_next_after"]


def naive_next_after(
    expression: Union[str, CronExpr],
    after: datetime,
    count: int = 1,
    horizon_years: int = MAX_HORIZON_YEARS,
) -> List[datetime]:
    """Scan forward one resolution step at a time until ``count`` matches.

    Args:
        expression: A crontab expression or a parsed :class:`CronExpr`.
        after: Naive datetime; occurrences are strictly later.
        count: Maximum number of occurrences to return.
        horizon_years: How far past ``after.year`` the scan may run.

    Returns:
        A list of naive datetimes, identical to
        :meth:`CronExpr.next_after`.
    """
    expr = CronExpr.parse(expression) if isinstance(expression, str) else expression
    if count < 0:
        raise ValueError("count must not be negative")
    if count == 0:
        return []

    step = expr.resolution
    cursor = (after + step).replace(microsecond=0)
    last_year = after.year + horizon_years
    results: List[datetime] = []
    while cursor.year <= last_year:
        if expr.matches(cursor):
            results.append(cursor)
            if len(results) == count:
                return results
        cursor += step
    return results
