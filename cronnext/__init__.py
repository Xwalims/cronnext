"""cronnext - compute the next fire times of a standard crontab expression.

Typical use::

    >>> from cronnext import next_after
    >>> from datetime import datetime
    >>> next_after("*/15 * * * *", datetime(2024, 1, 1, 0, 7), 3, tz="UTC")
    [datetime.datetime(2024, 1, 1, 0, 15, tzinfo=zoneinfo.ZoneInfo(key='UTC')), ...]
"""

from __future__ import annotations

from .expr import ALIASES, MAX_HORIZON_YEARS, CronError, CronExpr, cron_dow, resolve
from .fields import MONTH_NAMES, WEEKDAY_NAMES, Field, FieldError
from .next import TimezoneError, get_zone, next_after, to_utc

__all__ = [
    "ALIASES",
    "MAX_HORIZON_YEARS",
    "MONTH_NAMES",
    "WEEKDAY_NAMES",
    "CronError",
    "CronExpr",
    "Field",
    "FieldError",
    "TimezoneError",
    "__version__",
    "cron_dow",
    "get_zone",
    "next_after",
    "resolve",
    "to_utc",
]

__version__ = "0.1.0"
