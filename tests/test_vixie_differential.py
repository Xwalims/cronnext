"""Differential tests against an independent port of vixie-cron.

``tests/naive.py`` proves the smart-skip search agrees with a minute-by-minute
scan, but both call the *same* ``CronExpr.day_matches``, so that pair cannot
catch a day rule that is wrong in both.  These tests compare against
:mod:`tests.vixie_oracle`, which shares no code with the library.
"""

import unittest
from datetime import date, datetime, timedelta

from cronnext.expr import CronExpr, cron_dow
from tests.vixie_oracle import vixie_accepts, vixie_day_matches

#: Pairs of day-of-month / day-of-week fields, chosen to cover the wildcard
#: rule: both bare stars, one star, no star, a leading-star step, and lists
#: that merely begin with a star.
DAY_FIELDS = [
    ("*", "*"),
    ("*", "1"),
    ("1", "1"),
    ("1", "*"),
    ("*/2", "1"),
    ("*/3", "1"),
    ("1", "*/2"),
    ("1", "*/3"),
    ("*/2", "*/2"),
    ("1-15", "1"),
    ("*,7", "1"),
    ("1", "*,7"),
    ("*/7", "2-4"),
    ("15", "*/3"),
    ("*/2", "1-5"),
    ("1,15", "0"),
    ("*/2", "0"),
    ("2", "*/2"),
    ("*/2", "*"),
    ("*", "*/2"),
    ("7", "*"),
    ("*", "7"),
    ("1", "*/7"),
    ("*", "*/7"),
    ("*/3", "1,15"),
]

#: Day-field pairs that exercise a documented cronnext extension rather than
#: vixie behaviour, so there is no vixie verdict to compare against.
#:
#: ``6-0`` is a descending range.  vixie parses it and sets no bits, so the
#: job never fires; cronnext wraps it to Sat, Sun.  Confirmed against both
#: vixie-cron 3.0pl1 builds: 0 firings over a year.  The dedicated
#: TestDescendingRangesDifferFromVixie class pins this divergence directly.
EXTENSION_ONLY = {("*", "6-0"), ("1", "6-0")}


def _days(start, count):
    return [start + timedelta(days=offset) for offset in range(count)]


class TestDayRuleMatchesVixie(unittest.TestCase):
    """The day rule must agree with cron.c on every day of a leap year."""

    def test_agrees_over_a_whole_leap_year(self):
        mismatches = []
        for dom_text, dow_text in DAY_FIELDS:
            if (dom_text, dow_text) in EXTENSION_ONLY:
                continue
            if not vixie_accepts(dom_text, dow_text):
                # vixie rejects this pair outright, so there is no behaviour
                # to compare against; a separate test covers acceptance.
                continue
            expr = CronExpr.parse(f"0 0 {dom_text} * {dow_text}")
            for day in _days(date(2024, 1, 1), 366):
                moment = datetime(day.year, day.month, day.day)
                mine = expr.day_matches(moment)
                theirs = vixie_day_matches(
                    dom_text, dow_text, day.day, cron_dow(moment)
                )
                if mine != theirs:
                    mismatches.append(
                        f"{dom_text!r}/{dow_text!r} on {day}: "
                        f"cronnext={mine} vixie={theirs}"
                    )
        self.assertEqual(mismatches, [], "\n".join(mismatches[:10]))

    def test_leading_star_field_is_treated_as_a_wildcard(self):
        # entry.c sets DOM_STAR when the field starts with '*', so '*\/2' is a
        # wildcard: the two day fields combine with AND, not OR.
        expr = CronExpr.parse("0 0 */2 * 1")
        self.assertTrue(expr.days_of_month.star)
        # 2024-01-01 is a Monday and an odd day: both halves agree.
        self.assertTrue(expr.day_matches(datetime(2024, 1, 1)))
        # 2024-01-08 is a Monday but an even day: AND rejects it, even though
        # the weekday alone would match under the OR reading.
        self.assertFalse(expr.day_matches(datetime(2024, 1, 8)))

    def test_stepped_weekday_field_is_also_a_wildcard(self):
        expr = CronExpr.parse("0 0 15 * */2")
        self.assertTrue(expr.days_of_week.star)
        self.assertFalse(expr.days_of_month.star)
        # '*/2' covers the even vixie weekdays {0, 2, 4, 6}, so the AND keeps
        # only the 15ths that land on Sun, Tue, Thu or Sat.  15 January 2024
        # is a Monday and is correctly absent.
        found = [
            moment.date().isoformat()
            for moment in expr.next_after(datetime(2024, 1, 1), 4)
        ]
        self.assertEqual(
            found, ["2024-02-15", "2024-06-15", "2024-08-15", "2024-09-15"]
        )

    def test_bare_star_still_means_every_day(self):
        # The regression guard for the fix: with both fields bare stars the
        # rule stays an AND of two fields that always match.
        expr = CronExpr.parse("0 0 * * *")
        for day in _days(date(2024, 2, 27), 5):
            moment = datetime(day.year, day.month, day.day)
            self.assertTrue(expr.day_matches(moment))

    def test_neither_wildcard_stays_an_or(self):
        # 0 0 13 * FRI: every Friday and every 13th.
        expr = CronExpr.parse("0 0 13 * 5")
        found = [
            moment.date().isoformat()
            for moment in expr.next_after(datetime(2024, 9, 1), 4)
        ]
        self.assertEqual(
            found, ["2024-09-06", "2024-09-13", "2024-09-20", "2024-09-27"]
        )


class TestDescendingRangesDifferFromVixie(unittest.TestCase):
    """cronnext's wrapped range is an extension, not vixie behaviour.

    vixie-cron neither wraps nor rejects a descending range.  Upstream
    ``get_range()`` ends with::

        for (i = num1;  i <= num2;  i += num3)
                if (EOF == set_element(bits, low, high, i))
                        return EOF;

    which never executes when ``num1 > num2``, so the field keeps no bits at
    all.  The line parses, is accepted, and the job never runs.  This was
    checked against vixie-cron 3.0pl1 built from the upstream tarball and
    against Debian's 3.0pl1-184ubuntu2: ``0 0 * * 5-1``, ``0 0 * * 6-0`` and
    ``0 0 * * 5-1/2`` fire 0 times over 365 days of 2026, while ``0 0 * * 1``
    fires 52 times.

    These tests pin the *documented* extension so it cannot drift silently;
    they deliberately do not compare occurrences against the oracle, because
    vixie has no occurrence to compare against.
    """

    def test_vixie_accepts_a_descending_range(self):
        # Accepted as syntax, but it selects nothing -- that is the distinction
        # the previous version of this test got wrong by calling it a syntax
        # error.  vixie_accepts() must therefore say yes...
        self.assertTrue(vixie_accepts("*", "5-1"))
        self.assertTrue(vixie_accepts("*", "6-0"))
        # ...while the day rule must then never match on account of it.
        for weekday in range(7):
            self.assertFalse(
                vixie_day_matches("*", "5-1", 15, weekday),
                f"descending 5-1 matched on weekday {weekday}",
            )

    def test_a_descending_element_empties_only_its_own_field(self):
        # vixie sets bits per item, so a list keeps the bits from its valid
        # elements: '1,5-1' still means every Monday.
        for weekday in range(7):
            expected = weekday == 1
            self.assertEqual(
                vixie_day_matches("*", "1,5-1", 15, weekday), expected
            )

    def test_cronnext_wraps_as_documented(self):
        expr = CronExpr.parse("0 0 * * 5-1")
        self.assertEqual(
            sorted(expr.days_of_week.values), [0, 1, 5, 6]
        )

    def test_cronnext_wrap_survives_a_step(self):
        # README: '5-1/2' is Friday and Sunday.
        expr = CronExpr.parse("0 0 * * 5-1/2")
        self.assertEqual(sorted(expr.days_of_week.values), [0, 5])


if __name__ == "__main__":
    unittest.main()