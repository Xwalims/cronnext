"""The parsed crontab expression and its occurrence matching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .fields import MONTH_NAMES, WEEKDAY_NAMES, Field, FieldError, normalize_sunday

__all__ = [
    "ALIASES",
    "CronExpr",
    "CronError",
    "MAX_HORIZON_YEARS",
    "cron_dow",
    "resolve",
]

#: Default upper bound, in years, of a forward search from the start
#: datetime.  Eight years covers the worst realistic gap in the calendar:
#: February 29th is eight years away from a February 29th that falls on a
#: century year such as 2100, which is not a leap year.
MAX_HORIZON_YEARS = 8


class CronError(ValueError):
    """Raised when a whole crontab expression cannot be parsed."""


#: Nicknames accepted in place of the five field form.
ALIASES: Dict[str, str] = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}


def cron_dow(moment: datetime) -> int:
    """Return the vixie-cron weekday number of ``moment``.

    Python's :meth:`datetime.date.weekday` counts Monday as 0; cron counts
    Sunday as 0, so the value is rotated by one.
    """
    return (moment.weekday() + 1) % 7


def _start_of_next_month(moment: datetime, month: int) -> datetime:
    """Return midnight of the first day of the next occurrence of ``month``.

    ``month`` must be a value of the expression's month field that lies in
    the future relative to ``moment``; the returned datetime is in the same
    year when ``month`` has not passed yet and in the next year otherwise.
    """
    if month > moment.month:
        return moment.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0, month=month
        )
    return moment.replace(
        year=moment.year + 1,
        month=month,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


@dataclass(frozen=True)
class CronExpr:
    """A parsed crontab expression.

    Attributes:
        seconds: Optional seconds :class:`~cronnext.fields.Field`; when the
            expression carried six fields it is the leading field.
        minutes, hours, days_of_month, months, days_of_week: The five
            standard fields.
        text: The expression as it was written, whitespace collapsed.
    """

    minutes: Field
    hours: Field
    days_of_month: Field
    months: Field
    days_of_week: Field
    seconds: Optional[Field] = None
    text: str = ""

    # -- parsing ---------------------------------------------------------

    @classmethod
    def parse(cls, text: str) -> "CronExpr":
        """Parse ``text`` into a :class:`CronExpr`.

        Args:
            text: A crontab expression: either one of the ``@alias``
                nicknames, or five whitespace separated fields, or six
                fields whose first one is the seconds field.

        Returns:
            The parsed expression.

        Raises:
            CronError: If the expression is empty or malformed.
        """
        if text is None:
            raise CronError("expression is empty")
        collapsed = " ".join(text.split())
        if not collapsed:
            raise CronError("expression is empty")

        lowered = collapsed.lower()
        if lowered.startswith("@"):
            expanded = ALIASES.get(lowered)
            if expanded is None:
                raise CronError(f"unknown alias {collapsed!r}")
            collapsed = expanded
            lowered = collapsed.lower()

        parts = collapsed.split(" ")
        if len(parts) not in (5, 6):
            raise CronError(
                f"expected 5 or 6 fields, got {len(parts)}: {text!r}"
            )

        try:
            if len(parts) == 6:
                seconds = Field.parse("seconds", parts[0], 0, 59)
                offset = 1
            else:
                seconds = None
                offset = 0
            minutes = Field.parse("minute", parts[offset + 0], 0, 59)
            hours = Field.parse("hour", parts[offset + 1], 0, 23)
            days_of_month = Field.parse("day of month", parts[offset + 2], 1, 31)
            months = Field.parse(
                "month", parts[offset + 3], 1, 12, names=MONTH_NAMES
            )
            days_of_week = Field.parse(
                "day of week",
                parts[offset + 4],
                0,
                7,
                names=WEEKDAY_NAMES,
                normalize=normalize_sunday,
                star_maximum=6,
            )
        except FieldError as error:
            raise CronError(str(error)) from error

        return cls(
            minutes=minutes,
            hours=hours,
            days_of_month=days_of_month,
            months=months,
            days_of_week=days_of_week,
            seconds=seconds,
            text=" ".join(collapsed.split()),
        )

    # -- matching --------------------------------------------------------

    def matches(self, moment: datetime) -> bool:
        """Return True when ``moment`` is an occurrence of this expression.

        The datetime is read as a wall clock time; no timezone conversion is
        performed.
        """
        if self.minutes is None or not self.minutes.contains(moment.minute):
            return False
        if not self.hours.contains(moment.hour):
            return False
        if not self.months.contains(moment.month):
            return False
        if self.seconds is not None and not self.seconds.contains(moment.second):
            return False
        return self.day_matches(moment)

    def day_matches(self, moment: datetime) -> bool:
        """Return True when the day part of the expression matches.

        vixie-cron combines the two day fields with a single rule, and cron.c
        spells it out::

            ((e->flags & (DOM_STAR|DOW_STAR)) != 0)
                 ? (thisdom && thisdow)
                 : (thisdom || thisdow)

        So the day matches when **either** field is a wildcard, and only then
        is the match an AND.  With neither field a wildcard it is an OR, which
        is why ``0 0 1 * 0`` (the first of the month, or any Sunday) really
        does fire on every Sunday.

        "Wildcard" here is a property of the field *text*, not of its
        expanded values: entry.c tests ``ch == '*'`` on the field's first
        character, so ``*/2`` and ``*,7`` are wildcards as well.  ``0 0 */2 *
        1`` therefore means "an odd day of the month **and** a Monday", not
        "an odd day, or any Monday".
        """
        by_month = self.days_of_month.contains(moment.day)
        by_week = self.days_of_week.contains(cron_dow(moment))
        if self.days_of_month.star or self.days_of_week.star:
            return by_month and by_week
        return by_month or by_week

    # -- forward search --------------------------------------------------

    @property
    def resolution(self) -> timedelta:
        """Smallest time step between two occurrences."""
        return timedelta(seconds=1) if self.seconds is not None else timedelta(minutes=1)

    def next_after(
        self, after: datetime, count: int = 1, horizon_years: int = MAX_HORIZON_YEARS
    ) -> List[datetime]:
        """Return up to ``count`` occurrences strictly after ``after``.

        The search walks forward and skips whole units of time at a time: to
        the next matching minute, to the next matching hour at ``:00``, to
        the next day at ``00:00``, or to the first day of the next matching
        month.  Because every skip only jumps over instants that cannot
        match, the result is identical to a naive minute-by-minute scan.

        Args:
            after: Naive wall clock datetime; occurrences are strictly later.
            count: Maximum number of occurrences to return.
            horizon_years: How far past ``after.year`` the search may run.

        Returns:
            A strictly increasing list of naive datetimes.  It is shorter
            than ``count`` when the expression has no further occurrence
            within the horizon, which happens for expressions such as
            ``0 0 30 2 *`` that can never fire.
        """
        if count < 0:
            raise ValueError("count must not be negative")
        if count == 0:
            return []
        if after.tzinfo is not None:
            raise ValueError(
                "next_after expects a naive datetime; use cronnext.next for "
                "timezone aware searching"
            )

        last_year = after.year + horizon_years
        cursor = after + self.resolution
        cursor = cursor.replace(microsecond=0)

        results: List[datetime] = []
        while cursor.year <= last_year:
            moment = self._advance(cursor, last_year)
            if moment is None or moment.year > last_year:
                break
            results.append(moment)
            if len(results) == count:
                return results
            cursor = moment + self.resolution
        return results

    def _advance(self, cursor: datetime, limit_year: int) -> Optional[datetime]:
        """Return the first occurrence at or after ``cursor``.

        Every branch either confirms the moment or jumps it forward past
        time that provably cannot match, so the caller only ever sees a
        moment that satisfies every field.

        Args:
            cursor: Naive wall clock moment to search from, inclusive.
            limit_year: Largest year the caller is willing to return.

        Returns:
            The occurrence, or None when the moment could not be confirmed
            within ``limit_year``.  None is returned for expressions that
            can never fire, such as ``0 0 30 2 *``, which would otherwise
            walk the calendar to the year 10000 and overflow.
        """
        moment = cursor
        while True:
            if not self.months.contains(moment.month):
                following = self.months.next_after(moment.month)
                year = moment.year if following is not None else moment.year + 1
                if year > limit_year:
                    return None
                if following is None:
                    moment = moment.replace(
                        year=year,
                        month=1,
                        day=1,
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                else:
                    moment = moment.replace(
                        year=year,
                        month=following,
                        day=1,
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                continue

            if not self.day_matches(moment):
                if moment.year > limit_year:
                    return None
                moment = (moment + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                continue

            if not self.hours.contains(moment.hour):
                following = self.hours.next_after(moment.hour)
                if following is None:
                    if moment.year > limit_year:
                        return None
                    moment = (moment + timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    continue
                moment = moment.replace(
                    hour=following, minute=0, second=0, microsecond=0
                )
                continue

            if not self.minutes.contains(moment.minute):
                following = self.minutes.next_after(moment.minute)
                if following is None:
                    # No later minute matches today; the next hour may still
                    # carry a matching minute such as :00, so step there and
                    # let the loop re-check rather than skipping a whole day.
                    if moment.year > limit_year:
                        return None
                    moment = (moment + timedelta(hours=1)).replace(
                        minute=0, second=0, microsecond=0
                    )
                    continue
                moment = moment.replace(minute=following, second=0, microsecond=0)
                continue

            if self.seconds is not None and not self.seconds.contains(moment.second):
                following = self.seconds.next_after(moment.second)
                if following is None:
                    if moment.year > limit_year:
                        return None
                    moment = (moment + timedelta(minutes=1)).replace(
                        second=0, microsecond=0
                    )
                    continue
                moment = moment.replace(second=following, microsecond=0)
                continue

            return moment

    def describe(self) -> str:
        """Return the expression in the canonical five or six field form."""
        parts: List[str] = []
        if self.seconds is not None:
            parts.append(self.seconds.text)
        parts.extend(
            [
                self.minutes.text,
                self.hours.text,
                self.days_of_month.text,
                self.months.text,
                self.days_of_week.text,
            ]
        )
        return " ".join(parts)


def resolve(text: str) -> CronExpr:
    """Parse ``text`` into a :class:`CronExpr`.

    Convenience wrapper around :meth:`CronExpr.parse` that reports parse
    failures as :class:`CronError`.

    Args:
        text: The crontab expression.

    Returns:
        The parsed expression.
    """
    return CronExpr.parse(text)
