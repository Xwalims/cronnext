"""Tests for :mod:`cronnext.expr`: parsing, aliases and matching."""

import unittest
from datetime import datetime

from cronnext.expr import ALIASES, CronError, CronExpr, cron_dow, resolve


class TestParsing(unittest.TestCase):
    """Splitting an expression into fields."""

    def test_five_fields(self):
        expr = CronExpr.parse("*/15 * * * *")
        self.assertEqual(expr.minutes.sorted_values(), (0, 15, 30, 45))
        self.assertEqual(expr.hours.sorted_values(), tuple(range(24)))
        self.assertIsNone(expr.seconds)

    def test_six_fields(self):
        # 30 seconds past the minute, every second minute, every hour.
        expr = CronExpr.parse("30 */2 * * * *")
        self.assertEqual(expr.seconds.sorted_values(), (30,))
        self.assertEqual(
            expr.minutes.sorted_values(), tuple(range(0, 60, 2))
        )
        self.assertEqual(expr.hours.sorted_values(), tuple(range(24)))

    def test_extra_whitespace_collapsed(self):
        expr = CronExpr.parse("  0   3  *  *  1-5  ")
        self.assertEqual(expr.text, "0 3 * * 1-5")

    def test_surrounding_newlines_tolerated(self):
        self.assertEqual(CronExpr.parse("\n0 0 1 1 *\n").text, "0 0 1 1 *")

    def test_too_few_fields(self):
        with self.assertRaises(CronError):
            CronExpr.parse("0 3 * *")

    def test_too_many_fields(self):
        with self.assertRaises(CronError):
            CronExpr.parse("0 0 0 0 3 * *")

    def test_empty_string(self):
        with self.assertRaises(CronError):
            CronExpr.parse("")

    def test_whitespace_only(self):
        with self.assertRaises(CronError):
            CronExpr.parse("   ")

    def test_none_rejected(self):
        with self.assertRaises(CronError):
            CronExpr.parse(None)

    def test_invalid_field_reported_as_cron_error(self):
        with self.assertRaises(CronError) as caught:
            CronExpr.parse("99 * * * *")
        self.assertIn("minute", str(caught.exception))

    def test_resolve_helper(self):
        self.assertEqual(resolve("@daily").text, "0 0 * * *")

    def test_describe_six_fields(self):
        self.assertEqual(CronExpr.parse("15 0 3 * * 1").describe(), "15 0 3 * * 1")

    def test_describe_five_fields(self):
        self.assertEqual(CronExpr.parse("0 3 * * 1-5").describe(), "0 3 * * 1-5")


class TestAliases(unittest.TestCase):
    """Every @nickname expands to the right five field form."""

    def test_yearly(self):
        self.assertEqual(CronExpr.parse("@yearly").describe(), "0 0 1 1 *")

    def test_annually(self):
        self.assertEqual(CronExpr.parse("@annually").describe(), "0 0 1 1 *")

    def test_monthly(self):
        self.assertEqual(CronExpr.parse("@monthly").describe(), "0 0 1 * *")

    def test_weekly(self):
        self.assertEqual(CronExpr.parse("@weekly").describe(), "0 0 * * 0")

    def test_daily(self):
        self.assertEqual(CronExpr.parse("@daily").describe(), "0 0 * * *")

    def test_midnight(self):
        self.assertEqual(CronExpr.parse("@midnight").describe(), "0 0 * * *")

    def test_hourly(self):
        self.assertEqual(CronExpr.parse("@hourly").describe(), "0 * * * *")

    def test_aliases_are_case_insensitive(self):
        self.assertEqual(CronExpr.parse("@Daily").describe(), "0 0 * * *")

    def test_all_aliases_table_is_complete(self):
        self.assertEqual(len(ALIASES), 7)

    def test_unknown_alias_rejected(self):
        with self.assertRaises(CronError):
            CronExpr.parse("@fortnightly")

    def test_alias_expands_to_matching_expression(self):
        alias = CronExpr.parse("@weekly")
        expanded = CronExpr.parse(ALIASES["@weekly"])
        moment = datetime(2024, 1, 7, 0, 0)
        self.assertEqual(alias.matches(moment), expanded.matches(moment))


class TestCronDow(unittest.TestCase):
    """The Sunday-is-zero weekday numbering."""

    def test_monday_is_one(self):
        self.assertEqual(cron_dow(datetime(2024, 1, 1)), 1)

    def test_sunday_is_zero(self):
        self.assertEqual(cron_dow(datetime(2024, 1, 7)), 0)

    def test_saturday_is_six(self):
        self.assertEqual(cron_dow(datetime(2024, 1, 6)), 6)

    def test_full_week_is_a_permutation(self):
        week = [cron_dow(datetime(2024, 1, 1) .replace(day=day)) for day in range(1, 8)]
        self.assertEqual(sorted(week), list(range(7)))


class TestMatches(unittest.TestCase):
    """Wall clock matching of every field."""

    def test_every_minute_matches_everything(self):
        expr = CronExpr.parse("* * * * *")
        self.assertTrue(expr.matches(datetime(2024, 5, 17, 13, 42)))

    def test_exact_minute_matches(self):
        expr = CronExpr.parse("0 * * * *")
        self.assertTrue(expr.matches(datetime(2024, 5, 17, 13, 0)))
        self.assertFalse(expr.matches(datetime(2024, 5, 17, 13, 1)))

    def test_hour_list(self):
        expr = CronExpr.parse("0 3,15 * * *")
        self.assertTrue(expr.matches(datetime(2024, 5, 17, 15, 0)))
        self.assertFalse(expr.matches(datetime(2024, 5, 17, 4, 0)))

    def test_month_name_match(self):
        expr = CronExpr.parse("0 0 1 mar *")
        self.assertTrue(expr.matches(datetime(2024, 3, 1, 0, 0)))
        self.assertFalse(expr.matches(datetime(2024, 4, 1, 0, 0)))

    def test_day_of_week_name_match(self):
        expr = CronExpr.parse("0 0 * * MON")
        self.assertTrue(expr.matches(datetime(2024, 1, 1)))
        self.assertFalse(expr.matches(datetime(2024, 1, 2)))

    def test_sunday_spelled_seven(self):
        expr = CronExpr.parse("0 0 * * 7")
        self.assertTrue(expr.matches(datetime(2024, 1, 7)))

    def test_sunday_spelled_zero(self):
        expr = CronExpr.parse("0 0 * * 0")
        self.assertTrue(expr.matches(datetime(2024, 1, 7)))

    def test_seconds_field_match(self):
        expr = CronExpr.parse("*/15 * * * * *")
        self.assertTrue(expr.matches(datetime(2024, 5, 17, 13, 0, 15)))
        self.assertFalse(expr.matches(datetime(2024, 5, 17, 13, 0, 16)))

    def test_seconds_zero_every_minute(self):
        expr = CronExpr.parse("0 * * * * *")
        self.assertTrue(expr.matches(datetime(2024, 5, 17, 13, 1, 0)))
        self.assertFalse(expr.matches(datetime(2024, 5, 17, 13, 1, 1)))

    def test_seconds_and_minute_both_zero(self):
        expr = CronExpr.parse("0 0 * * * *")
        self.assertTrue(expr.matches(datetime(2024, 5, 17, 13, 0, 0)))
        self.assertFalse(expr.matches(datetime(2024, 5, 17, 13, 1, 0)))

    def test_seconds_resolution(self):
        self.assertEqual(CronExpr.parse("* * * * *").resolution.total_seconds(), 60)
        self.assertEqual(
            CronExpr.parse("* * * * * *").resolution.total_seconds(), 1
        )

    def test_resolution_is_timedelta(self):
        self.assertEqual(str(CronExpr.parse("* * * * *").resolution), "0:01:00")


class TestDayRule(unittest.TestCase):
    """Day-of-month and day-of-week combine with OR, in both directions."""

    def test_both_restricted_matches_either(self):
        expr = CronExpr.parse("0 0 13 * FRI")
        # the 13th, or any Friday, whichever comes first
        self.assertTrue(expr.matches(datetime(2024, 9, 13, 0, 0)))  # Friday
        self.assertTrue(expr.matches(datetime(2024, 10, 13, 0, 0)))  # Sunday
        self.assertFalse(expr.matches(datetime(2024, 10, 14, 0, 0)))

    def test_day_of_month_alone_when_week_is_star(self):
        expr = CronExpr.parse("0 0 1 * *")
        self.assertTrue(expr.matches(datetime(2024, 1, 1)))
        self.assertFalse(expr.matches(datetime(2024, 1, 7)))

    def test_day_of_week_alone_when_month_day_is_star(self):
        expr = CronExpr.parse("0 0 * * SUN")
        self.assertTrue(expr.matches(datetime(2024, 1, 7)))
        self.assertFalse(expr.matches(datetime(2024, 1, 1)))

    def test_first_of_month_or_sunday_fires_every_sunday(self):
        expr = CronExpr.parse("0 0 1 * 0")
        sundays = [
            moment.date()
            for moment in (datetime(2024, 1, 1).replace(day=d) for d in range(1, 32))
            if expr.matches(moment)
        ]
        self.assertIn(datetime(2024, 1, 7).date(), sundays)
        self.assertIn(datetime(2024, 1, 14).date(), sundays)
        self.assertIn(datetime(2024, 1, 28).date(), sundays)

    def test_rule_does_not_and_the_days_together(self):
        expr = CronExpr.parse("0 0 1 * 0")
        # 2 March 2024 is a Saturday: neither the first of the month nor a
        # Sunday, so the union must reject it.
        self.assertFalse(expr.day_matches(datetime(2024, 3, 2)))
        # 1 March 2024 is the first of the month, so the day-of-month half
        # of the union carries it even though it is a Friday.
        self.assertTrue(expr.day_matches(datetime(2024, 3, 1)))

    def test_union_never_needs_both_halves(self):
        expr = CronExpr.parse("0 0 15 * MON")
        # 15 July 2024 is a Monday: both halves agree.
        self.assertTrue(expr.day_matches(datetime(2024, 7, 15)))
        # 14 July 2024 is a Sunday: neither half agrees.
        self.assertFalse(expr.day_matches(datetime(2024, 7, 14)))

    def test_star_in_both_day_fields_matches_every_day(self):
        expr = CronExpr.parse("0 0 * * *")
        self.assertTrue(expr.day_matches(datetime(2024, 1, 3)))
        self.assertTrue(expr.day_matches(datetime(2024, 1, 4)))

    def test_day_matches_ignores_time(self):
        expr = CronExpr.parse("0 0 * * *")
        self.assertTrue(expr.day_matches(datetime(2024, 1, 3, 23, 59)))

    def test_weekday_step_field(self):
        expr = CronExpr.parse("0 0 * * 1/2")
        # 1/2 is Mon, Wed, Fri
        self.assertTrue(expr.matches(datetime(2024, 1, 3)))  # Wednesday
        self.assertFalse(expr.matches(datetime(2024, 1, 4)))  # Thursday


if __name__ == "__main__":
    unittest.main()
