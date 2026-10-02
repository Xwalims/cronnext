"""Tests for the occurrence search: correctness, boundaries and equivalence."""

import unittest
from datetime import datetime, timedelta, timezone

from cronnext.expr import MAX_HORIZON_YEARS, CronExpr
from tests.naive import naive_next_after


def utc(moment):
    """Return ``moment`` as an aware UTC datetime."""
    return moment.replace(tzinfo=timezone.utc)


def as_utc_iso(moments):
    """Return an ISO 8601 UTC string for each naive moment in ``moments``."""
    return [utc(moment).isoformat().replace("+00:00", "Z") for moment in moments]


class TestNextAfterBasics(unittest.TestCase):
    """The happy path, checked against hand-computed timestamps."""

    def test_every_fifteen_minutes(self):
        expr = CronExpr.parse("*/15 * * * *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 1, 1, 0, 7), 5)),
            [
                "2024-01-01T00:15:00Z",
                "2024-01-01T00:30:00Z",
                "2024-01-01T00:45:00Z",
                "2024-01-01T01:00:00Z",
                "2024-01-01T01:15:00Z",
            ],
        )

    def test_weekday_at_three(self):
        expr = CronExpr.parse("0 3 * * 1-5")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 1, 5, 12, 0), 5)),
            [
                "2024-01-08T03:00:00Z",
                "2024-01-09T03:00:00Z",
                "2024-01-10T03:00:00Z",
                "2024-01-11T03:00:00Z",
                "2024-01-12T03:00:00Z",
            ],
        )

    def test_start_is_exclusive(self):
        expr = CronExpr.parse("0 12 * * *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 1, 1, 12, 0), 1)),
            ["2024-01-02T12:00:00Z"],
        )

    def test_start_one_second_before(self):
        expr = CronExpr.parse("0 12 * * *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 1, 1, 11, 59), 1)),
            ["2024-01-01T12:00:00Z"],
        )

    def test_microseconds_are_dropped(self):
        expr = CronExpr.parse("* * * * *")
        found = expr.next_after(datetime(2024, 1, 1, 0, 0, 0, 999999), 1)
        self.assertEqual(as_utc_iso(found), ["2024-01-01T00:01:00Z"])

    def test_count_zero_returns_empty(self):
        self.assertEqual(CronExpr.parse("* * * * *").next_after(datetime(2024, 1, 1), 0), [])

    def test_negative_count_rejected(self):
        with self.assertRaises(ValueError):
            CronExpr.parse("* * * * *").next_after(datetime(2024, 1, 1), -1)

    def test_aware_datetime_rejected(self):
        with self.assertRaises(ValueError):
            CronExpr.parse("* * * * *").next_after(utc(datetime(2024, 1, 1)), 1)


class TestSecondsField(unittest.TestCase):
    """The optional sixth field."""

    def test_seconds_every_thirty(self):
        expr = CronExpr.parse("*/30 * * * * *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 1, 1, 0, 0, 0), 4)),
            [
                "2024-01-01T00:00:30Z",
                "2024-01-01T00:01:00Z",
                "2024-01-01T00:01:30Z",
                "2024-01-01T00:02:00Z",
            ],
        )

    def test_top_of_each_minute(self):
        expr = CronExpr.parse("0 * * * * *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 1, 1, 0, 0, 30), 2)),
            ["2024-01-01T00:01:00Z", "2024-01-01T00:02:00Z"],
        )

    def test_second_twenty_of_the_hour(self):
        expr = CronExpr.parse("20 0 * * * *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 1, 1, 0, 0, 0), 2)),
            ["2024-01-01T00:00:20Z", "2024-01-01T01:00:20Z"],
        )


class TestCalendarBoundaries(unittest.TestCase):
    """Month rollover, leap days and year rollover."""

    def test_month_rollover(self):
        expr = CronExpr.parse("0 0 1 * *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 1, 15), 3)),
            [
                "2024-02-01T00:00:00Z",
                "2024-03-01T00:00:00Z",
                "2024-04-01T00:00:00Z",
            ],
        )

    def test_year_rollover(self):
        expr = CronExpr.parse("0 0 1 1 *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 6, 1), 3)),
            [
                "2025-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                "2027-01-01T00:00:00Z",
            ],
        )

    def test_leap_day_from_after_it(self):
        expr = CronExpr.parse("0 0 29 2 *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 3, 1), 2)),
            ["2028-02-29T00:00:00Z", "2032-02-29T00:00:00Z"],
        )

    def test_leap_day_from_before_it(self):
        expr = CronExpr.parse("0 0 29 2 *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2023, 6, 1), 2)),
            ["2024-02-29T00:00:00Z", "2028-02-29T00:00:00Z"],
        )

    def test_non_leap_february_skipped(self):
        expr = CronExpr.parse("0 0 29 2 *")
        for moment in expr.next_after(datetime(2023, 1, 1), 3):
            self.assertIn(moment.year % 4, (0,), "2024 is the next leap year")

    def test_horizon_reached_when_too_short(self):
        expr = CronExpr.parse("0 0 29 2 *")
        # The bound is start.year + horizon_years, so 2029 is the last year
        # reachable here and there is no leap day in 2026 or 2027.
        found = expr.next_after(datetime(2025, 1, 1), 1, horizon_years=2)
        self.assertEqual(found, [], "no leap day within two years of 2025")

    def test_horizon_exactly_reaches_next_leap_day(self):
        expr = CronExpr.parse("0 0 29 2 *")
        found = expr.next_after(datetime(2025, 1, 1), 1, horizon_years=3)
        self.assertEqual(
            [moment.date().isoformat() for moment in found], ["2028-02-29"]
        )

    def test_december_to_january(self):
        expr = CronExpr.parse("0 0 31 12 *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 12, 31, 12, 0), 2)),
            ["2025-12-31T00:00:00Z", "2026-12-31T00:00:00Z"],
        )

    def test_thirty_first_skips_short_months(self):
        expr = CronExpr.parse("0 0 31 * *")
        found = expr.next_after(datetime(2024, 1, 31, 1, 0), 3)
        self.assertEqual(
            as_utc_iso(found),
            [
                "2024-03-31T00:00:00Z",
                "2024-05-31T00:00:00Z",
                "2024-07-31T00:00:00Z",
            ],
        )

    def test_february_twenty_ninth_or_last_day(self):
        # 29 February only exists in leap years; the union with day-of-week
        # is not in play here, so check the plain day-of-month path.
        expr = CronExpr.parse("0 0 28 2 *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2023, 3, 1), 2)),
            ["2024-02-28T00:00:00Z", "2025-02-28T00:00:00Z"],
        )

    def test_hour_rollover_into_next_day(self):
        expr = CronExpr.parse("0 23 * * *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 1, 1, 23, 30), 2)),
            ["2024-01-02T23:00:00Z", "2024-01-03T23:00:00Z"],
        )

    def test_minute_rollover_into_next_hour(self):
        expr = CronExpr.parse("59 * * * *")
        self.assertEqual(
            as_utc_iso(expr.next_after(datetime(2024, 1, 1, 10, 59), 2)),
            ["2024-01-01T11:59:00Z", "2024-01-01T12:59:00Z"],
        )


class TestDayRuleInSearch(unittest.TestCase):
    """The OR rule drives the search, not just matching."""

    def test_first_of_month_or_sunday_sequence(self):
        expr = CronExpr.parse("0 0 1 * 0")
        self.assertEqual(
            [moment.date().isoformat() for moment in expr.next_after(datetime(2024, 1, 1), 6)],
            [
                "2024-01-07",
                "2024-01-14",
                "2024-01-21",
                "2024-01-28",
                "2024-02-01",
                "2024-02-04",
            ],
        )

    def test_thirteenth_or_friday(self):
        expr = CronExpr.parse("0 0 13 * 5")
        self.assertEqual(
            [moment.date().isoformat() for moment in expr.next_after(datetime(2024, 9, 1), 5)],
            ["2024-09-06", "2024-09-13", "2024-09-20", "2024-09-27", "2024-10-04"],
        )

    def test_friday_the_thirteenth_is_a_single_occurrence(self):
        expr = CronExpr.parse("0 0 13 * 5")
        found = expr.next_after(datetime(2024, 9, 13), 1)
        self.assertEqual(found[0].date().isoformat(), "2024-09-20")

    def test_friday_the_thirteenth_fires_once(self):
        # 13 September 2024 is a Friday: both halves of the union agree and
        # the day must be emitted exactly once.
        expr = CronExpr.parse("0 0 13 * 5")
        found = expr.next_after(datetime(2024, 9, 12), 2)
        self.assertEqual(
            [moment.date().isoformat() for moment in found],
            ["2024-09-13", "2024-09-20"],
        )

    def test_month_and_weekday_both_restricted_may_overlap(self):
        # 1 September 2024 is both the first and a Sunday; the union must
        # not emit it twice.
        expr = CronExpr.parse("0 0 1 * 0")
        found = expr.next_after(datetime(2024, 8, 31), 2)
        self.assertEqual(
            [moment.date().isoformat() for moment in found],
            ["2024-09-01", "2024-09-08"],
        )


class TestHorizonAndTermination(unittest.TestCase):
    """The search always terminates and respects its bound."""

    def test_impossible_date_returns_empty(self):
        # 30 February never occurs, so the search finds nothing at all.
        expr = CronExpr.parse("0 0 30 2 *")
        self.assertEqual(expr.next_after(datetime(2024, 1, 1), 5, horizon_years=4), [])

    def test_impossible_date_terminates_without_overflow(self):
        expr = CronExpr.parse("0 0 30 2 *")
        self.assertEqual(expr.next_after(datetime(2024, 1, 1), 1), [])

    def test_impossible_date_does_not_raise(self):
        expr = CronExpr.parse("0 0 31 2 *")
        self.assertEqual(expr.next_after(datetime(2024, 1, 1), 3, horizon_years=2), [])

    def test_default_horizon_is_eight_years(self):
        self.assertEqual(MAX_HORIZON_YEARS, 8)

    def test_february_thirtieth_never_matches(self):
        expr = CronExpr.parse("0 0 30 2 *")
        self.assertTrue(all(not expr.matches(m) for m in [
            datetime(2024, 2, 29), datetime(2023, 2, 28), datetime(2024, 2, 1)
        ]))

    def test_leap_day_finds_next_within_default_horizon(self):
        expr = CronExpr.parse("0 0 29 2 *")
        found = expr.next_after(datetime(2096, 3, 1), 1, horizon_years=8)
        self.assertEqual(found[0].date().isoformat(), "2104-02-29")

    def test_horizon_never_returns_a_year_past_the_bound(self):
        expr = CronExpr.parse("0 0 29 2 *")
        start = datetime(2024, 3, 1)
        for moment in expr.next_after(start, 10, horizon_years=8):
            self.assertLessEqual(moment.year, start.year + 8)

    def test_sparse_expression_terminates_quickly(self):
        # 29 February, or any Monday: sparse, but the union rule keeps the
        # Monday half alive, so the first results are ordinary Mondays in
        # February 2024.
        expr = CronExpr.parse("0 0 29 2 1")
        self.assertEqual(
            [moment.date().isoformat() for moment in expr.next_after(datetime(2024, 1, 1), 3)],
            ["2024-02-05", "2024-02-12", "2024-02-19"],
        )

    def test_february_29_that_is_also_a_monday(self):
        expr = CronExpr.parse("0 0 29 2 1")
        # The month field is still February, so the union is restricted to
        # Mondays in February plus the 29th itself.  Past 29 February 2044,
        # which is a Monday, only the Monday half remains.
        self.assertEqual(
            [moment.date().isoformat() for moment in expr.next_after(datetime(2044, 3, 1), 3, horizon_years=8)],
            ["2045-02-06", "2045-02-13", "2045-02-20"],
        )


class TestMonotonicity(unittest.TestCase):
    """Every returned sequence is strictly increasing."""

    EXPRESSIONS = [
        "* * * * *",
        "*/15 * * * *",
        "0 3 * * 1-5",
        "0 0 1 * 0",
        "0 0 13 * 5",
        "0 0 29 2 *",
        "30 4 1,15 * 1",
        "0 */6 * * *",
        "*/5 9-17 * * 1-5",
        "0 0 * * */3",
        "0 12 1 1 *",
        "15,45 * * * *",
        "0 0 31 * *",
        "5 0 * 8 *",
        "0 22 * * 1-5",
        "0 */30 * * * *",
    ]

    def test_sequences_are_strictly_increasing(self):
        for text in self.EXPRESSIONS:
            with self.subTest(expression=text):
                expr = CronExpr.parse(text)
                found = expr.next_after(datetime(2024, 1, 1), 25)
                for earlier, later in zip(found, found[1:]):
                    self.assertLess(earlier, later)

    def test_every_occurrence_matches_its_expression(self):
        for text in self.EXPRESSIONS:
            with self.subTest(expression=text):
                expr = CronExpr.parse(text)
                for moment in expr.next_after(datetime(2024, 1, 1), 25):
                    self.assertTrue(expr.matches(moment))

    def test_chained_search_repeats_the_sequence(self):
        for text in self.EXPRESSIONS:
            with self.subTest(expression=text):
                expr = CronExpr.parse(text)
                first = expr.next_after(datetime(2024, 1, 1), 10)
                second = expr.next_after(first[-1], 10)
                self.assertTrue(all(b > a for a, b in zip(first, second)))


class TestEquivalenceWithNaiveScan(unittest.TestCase):
    """The smart-skip search must agree with a minute-by-minute scan.

    Every result below is produced twice: once by the optimised search in
    :meth:`CronExpr.next_after` and once by :func:`tests.naive.naive_next_after`,
    which advances one minute at a time and simply checks ``matches``.
    """

    EXPRESSIONS = [
        "* * * * *",
        "*/15 * * * *",
        "0 3 * * 1-5",
        "0 0 1 * 0",
        "0 0 13 * 5",
        "0 0 29 2 *",
        "30 4 1,15 * 1",
        "0 */6 * * *",
        "*/5 9-17 * * 1-5",
        "0 0 * * */3",
        "0 12 1 1 *",
        "15,45 * * * *",
        "0 0 31 * *",
        "5 0 * 8 *",
        "0 22 * * 1-5",
        "59 23 31 12 *",
        "0 0 * 2-6 1",
        "*/7 2-4 * * 2-4",
        "0 0 1,15 3,9 * 0",
        "0 0 * * 6-0",
    ]

    def test_matches_naive_scan_for_twelve_months(self):
        start = datetime(2024, 1, 1)
        for text in self.EXPRESSIONS:
            with self.subTest(expression=text):
                expr = CronExpr.parse(text)
                fast = expr.next_after(start, 20)
                slow = naive_next_after(expr, start, 20)
                self.assertEqual(fast, slow)

    def test_matches_naive_scan_from_many_start_points(self):
        starts = [
            datetime(2024, 1, 31, 23, 59),
            datetime(2024, 2, 29, 12, 0),
            datetime(2024, 6, 15, 0, 0),
            datetime(2024, 12, 31, 23, 58),
            datetime(2025, 3, 30, 1, 30),
        ]
        for text in self.EXPRESSIONS:
            expr = CronExpr.parse(text)
            for start in starts:
                with self.subTest(expression=text, start=start.isoformat()):
                    self.assertEqual(
                        expr.next_after(start, 10),
                        naive_next_after(expr, start, 10),
                    )

    def test_matches_naive_scan_with_seconds_field(self):
        start = datetime(2024, 1, 1)
        for text in ["*/30 * * * * *", "0 * * * * *", "15,45 */2 * * * *"]:
            with self.subTest(expression=text):
                expr = CronExpr.parse(text)
                self.assertEqual(
                    expr.next_after(start, 15),
                    naive_next_after(expr, start, 15),
                )

    def test_matches_naive_scan_across_leap_and_non_leap_years(self):
        for year in (2023, 2024, 2025, 2028):
            start = datetime(year, 2, 27)
            with self.subTest(year=year):
                expr = CronExpr.parse("0 0 29 2 *")
                self.assertEqual(
                    expr.next_after(start, 3),
                    naive_next_after(expr, start, 3),
                )

    def test_matches_naive_scan_on_short_horizon(self):
        start = datetime(2024, 1, 1)
        expr = CronExpr.parse("0 0 30 2 *")
        self.assertEqual(
            expr.next_after(start, 5, horizon_years=3),
            naive_next_after(expr, start, 5, horizon_years=3),
        )

    def test_dense_expression_agrees_at_high_volume(self):
        expr = CronExpr.parse("*/1 * * * *")
        start = datetime(2024, 5, 17, 13, 0)
        self.assertEqual(
            expr.next_after(start, 120),
            naive_next_after(expr, start, 120),
        )


if __name__ == "__main__":
    unittest.main()
