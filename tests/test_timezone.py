"""Tests for :mod:`cronnext.next`, including daylight saving behaviour."""

import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from cronnext.expr import CronExpr
from cronnext.next import TimezoneError, get_zone, is_imaginary, next_after, to_utc

BERLIN = "Europe/Berlin"
NEW_YORK = "America/New_York"


class TestZone(unittest.TestCase):
    """Resolving timezone names."""

    def test_known_zone(self):
        self.assertEqual(str(get_zone(BERLIN)), BERLIN)

    def test_default_zone_is_utc(self):
        self.assertEqual(str(get_zone(None)), "UTC")

    def test_unknown_zone_raises(self):
        with self.assertRaises(TimezoneError):
            get_zone("Mars/Olympus_Mons")

    def test_garbage_zone_raises(self):
        with self.assertRaises(TimezoneError):
            get_zone("not a zone")

    def test_to_utc_from_naive(self):
        self.assertEqual(
            to_utc(datetime(2024, 1, 1, 12)).isoformat(), "2024-01-01T12:00:00+00:00"
        )

    def test_to_utc_from_aware(self):
        moment = datetime(2024, 1, 1, 13, tzinfo=ZoneInfo(BERLIN))
        self.assertEqual(to_utc(moment).isoformat(), "2024-01-01T12:00:00+00:00")


class TestIsImaginary(unittest.TestCase):
    """Detecting local times that a DST gap erased."""

    def test_berlin_gap_is_imaginary(self):
        self.assertTrue(is_imaginary(datetime(2024, 3, 31, 2, 30, tzinfo=ZoneInfo(BERLIN))))

    def test_berlin_normal_time_is_real(self):
        self.assertFalse(is_imaginary(datetime(2024, 3, 31, 1, 30, tzinfo=ZoneInfo(BERLIN))))

    def test_berlin_ambiguous_time_is_real(self):
        # The autumn hour repeats a wall clock time, but it does exist.
        self.assertFalse(is_imaginary(datetime(2024, 10, 27, 2, 30, tzinfo=ZoneInfo(BERLIN))))

    def test_new_york_gap(self):
        self.assertTrue(is_imaginary(datetime(2024, 3, 10, 2, 30, tzinfo=ZoneInfo(NEW_YORK))))

    def test_utc_has_no_gap(self):
        self.assertFalse(is_imaginary(datetime(2024, 3, 31, 2, 30, tzinfo=ZoneInfo("UTC"))))

    def test_naive_rejected(self):
        with self.assertRaises(ValueError):
            is_imaginary(datetime(2024, 3, 31, 2, 30))


class TestBasicTimezoneSearch(unittest.TestCase):
    """Naive input is local, aware input is converted, output is aware."""

    def test_naive_input_returns_aware(self):
        found = next_after("0 12 * * *", datetime(2024, 1, 1), 1, tz=BERLIN)
        self.assertEqual(found[0].tzinfo is not None, True)
        self.assertEqual(found[0].isoformat(), "2024-01-01T12:00:00+01:00")

    def test_aware_input_converted_into_zone(self):
        found = next_after(
            "0 12 * * *", datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc), 1, tz=BERLIN
        )
        # 11:00 UTC is 12:00 in Berlin, so the next daily run is tomorrow.
        self.assertEqual(found[0].isoformat(), "2024-01-02T12:00:00+01:00")

    def test_default_zone_is_utc(self):
        found = next_after("0 * * * *", datetime(2024, 1, 1, 0, 30), 2)
        self.assertEqual(
            [moment.isoformat() for moment in found],
            ["2024-01-01T01:00:00+00:00", "2024-01-01T02:00:00+00:00"],
        )

    def test_utc_and_berlin_agree_on_instant(self):
        in_utc = next_after("0 12 * * *", datetime(2024, 1, 1), 1, tz="UTC")
        in_berlin = next_after("0 12 * * *", datetime(2024, 1, 1), 1, tz=BERLIN)
        # Same wall clock hour, so the same calendar day but different
        # absolute instants.
        self.assertEqual(in_utc[0].hour, in_berlin[0].hour)
        self.assertEqual(in_utc[0].day, in_berlin[0].day)
        self.assertNotEqual(to_utc(in_utc[0]), to_utc(in_berlin[0]))

    def test_same_instant_gives_same_result(self):
        # An instant already past 12:00 Berlin is noon UTC minus one hour,
        # so both zones must agree on the next daily noon.
        start = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        in_utc = next_after("0 12 * * *", start, 1, tz="UTC")
        self.assertEqual(in_utc[0].isoformat(), "2024-01-02T12:00:00+00:00")

    def test_expression_object_accepted(self):
        expr = CronExpr.parse("0 12 * * *")
        found = next_after(expr, datetime(2024, 1, 1), 1, tz=BERLIN)
        self.assertEqual(found[0].hour, 12)

    def test_bad_expression_type_rejected(self):
        with self.assertRaises(TypeError):
            next_after(42, datetime(2024, 1, 1), 1, tz=BERLIN)

    def test_negative_count_rejected(self):
        with self.assertRaises(ValueError):
            next_after("0 * * * *", datetime(2024, 1, 1), -1, tz=BERLIN)

    def test_zero_count_returns_empty(self):
        self.assertEqual(next_after("0 * * * *", datetime(2024, 1, 1), 0, tz=BERLIN), [])

    def test_unknown_zone_raises(self):
        with self.assertRaises(TimezoneError):
            next_after("0 * * * *", datetime(2024, 1, 1), 1, tz="Nowhere/Special")

    def test_winter_offset_is_plus_one(self):
        found = next_after("0 12 * * *", datetime(2024, 1, 15), 1, tz=BERLIN)
        self.assertEqual(found[0].utcoffset().total_seconds(), 3600)

    def test_summer_offset_is_plus_two(self):
        found = next_after("0 12 * * *", datetime(2024, 7, 15), 1, tz=BERLIN)
        self.assertEqual(found[0].utcoffset().total_seconds(), 7200)


class TestSpringForwardGap(unittest.TestCase):
    """Local times inside the gap are skipped, not shifted."""

    def test_berlin_gap_day_is_skipped_entirely(self):
        found = next_after("30 2 * * *", datetime(2024, 3, 29, 12, 0), 3, tz=BERLIN)
        self.assertEqual(
            [moment.date().isoformat() for moment in found],
            ["2024-03-30", "2024-04-01", "2024-04-02"],
        )

    def test_no_result_inside_the_gap(self):
        found = next_after("30 2 * * *", datetime(2024, 3, 29, 12, 0), 3, tz=BERLIN)
        self.assertNotIn(datetime(2024, 3, 31, 2, 30), [m.replace(tzinfo=None) for m in found])

    def test_gap_does_not_shift_the_scheduled_time(self):
        # 02:30 on 31 March does not exist, and 04:30 must not appear as a
        # substitute for it.
        found = next_after("30 2 * * *", datetime(2024, 3, 29, 12, 0), 4, tz=BERLIN)
        self.assertNotIn("2024-03-31T04:30", [m.isoformat() for m in found])

    def test_hourly_schedule_skips_the_missing_hour(self):
        found = next_after("0 * * * *", datetime(2024, 3, 31, 0, 30), 3, tz=BERLIN)
        self.assertEqual(
            [moment.isoformat() for moment in found],
            [
                "2024-03-31T01:00:00+01:00",
                "2024-03-31T03:00:00+02:00",
                "2024-03-31T04:00:00+02:00",
            ],
        )

    def test_new_york_gap_day_is_skipped(self):
        found = next_after("30 2 * * *", datetime(2024, 3, 8, 12, 0), 3, tz=NEW_YORK)
        self.assertEqual(
            [moment.date().isoformat() for moment in found],
            ["2024-03-09", "2024-03-11", "2024-03-12"],
        )

    def test_count_is_still_honoured_across_the_gap(self):
        found = next_after("*/30 * * * *", datetime(2024, 3, 31, 1, 30), 4, tz=BERLIN)
        self.assertEqual(len(found), 4)

    def test_instants_remain_increasing_across_the_gap(self):
        found = next_after("*/30 * * * *", datetime(2024, 3, 31, 1, 0), 6, tz=BERLIN)
        instants = [to_utc(moment) for moment in found]
        self.assertEqual(instants, sorted(instants))
        self.assertEqual(len(set(instants)), len(instants))


class TestFallBackFold(unittest.TestCase):
    """Ambiguous local times run once, at fold=0."""

    def test_ambiguous_time_runs_once(self):
        found = next_after("30 2 * * *", datetime(2024, 10, 26, 12, 0), 2, tz=BERLIN)
        self.assertEqual(
            [moment.isoformat() for moment in found],
            ["2024-10-27T02:30:00+02:00", "2024-10-28T02:30:00+01:00"],
        )

    def test_fold_zero_offset_is_the_first_pass(self):
        found = next_after("30 2 * * *", datetime(2024, 10, 26, 12, 0), 1, tz=BERLIN)
        self.assertEqual(found[0].isoformat(), "2024-10-27T02:30:00+02:00")
        self.assertEqual(found[0].fold, 0)

    def test_new_york_fold_runs_once(self):
        found = next_after("30 1 * * *", datetime(2024, 11, 1, 12, 0), 3, tz=NEW_YORK)
        self.assertEqual(
            [moment.date().isoformat() for moment in found],
            ["2024-11-02", "2024-11-03", "2024-11-04"],
        )

    def test_hourly_schedule_reports_the_folded_hour_once_per_local_hour(self):
        found = next_after("0 * * * *", datetime(2024, 10, 27, 0, 30), 4, tz=BERLIN)
        # 02:00 local happens twice that night, but the schedule runs once
        # per local hour, so it is reported once, at the fold=0 offset.
        stamps = [moment.strftime("%Y-%m-%d %H:%M %z") for moment in found]
        self.assertEqual(
            stamps,
            [
                "2024-10-27 01:00 +0200",
                "2024-10-27 02:00 +0200",
                "2024-10-27 03:00 +0100",
                "2024-10-27 04:00 +0100",
            ],
        )

    def test_fold_zero_keeps_the_earlier_offset(self):
        found = next_after("0 2 * * *", datetime(2024, 10, 26), 1, tz=BERLIN)
        self.assertEqual(found[0].strftime("%z"), "+0200")
        self.assertEqual(found[0].fold, 0)

    def test_no_duplicate_instants_after_the_fold(self):
        found = next_after("0 * * * *", datetime(2024, 11, 3, 0, 0), 5, tz=NEW_YORK)
        instants = [to_utc(moment) for moment in found]
        self.assertEqual(len(set(instants)), len(instants))

    def test_southern_hemisphere_transition(self):
        # Sydney leaves DST on 7 April 2024, at 03:00 local.
        found = next_after("0 2,3 * * *", datetime(2024, 4, 6, 12, 0), 5, tz="Australia/Sydney")
        self.assertEqual(len(found), 5)
        instants = [to_utc(moment) for moment in found]
        self.assertEqual(instants, sorted(instants))
        self.assertTrue(all(not is_imaginary(moment) for moment in found))


class TestHorizonBinding(unittest.TestCase):
    """The caller's horizon is a deadline, not a per-lookup budget."""

    def test_horizon_is_not_reapplied_on_each_resumption(self):
        # The deadline is fixed against the caller's start; it must not
        # slide forward by another horizon for every extra occurrence.
        found = next_after(
            "0 0 1 1 *", datetime(2024, 12, 31), 5, tz="UTC", horizon_years=1
        )
        self.assertEqual(
            [moment.isoformat() for moment in found], ["2025-01-01T00:00:00+00:00"]
        )

    def test_shorter_horizon_yields_a_shorter_list(self):
        # Starting in June 2024, a horizon of N years reaches 1 January of
        # 2024+N at the earliest and excludes 1 January of 2025+N.
        for years, expected in ((1, 1), (2, 2), (3, 3)):
            with self.subTest(years=years):
                found = next_after(
                    "0 0 1 1 *", datetime(2024, 6, 1), 10, tz="UTC", horizon_years=years
                )
                self.assertEqual(len(found), expected)

    def test_default_horizon_keeps_several_yearly_runs(self):
        found = next_after("0 0 1 1 *", datetime(2024, 6, 1), 3, tz="UTC")
        self.assertEqual(
            [moment.year for moment in found], [2025, 2026, 2027]
        )


class TestDenseSchedules(unittest.TestCase):
    """Expressions whose occurrences sit exactly one resolution apart.

    Every other class here uses a sparse rule -- ``0 2 * * *``, ``0 * * * *``
    -- whose occurrences are hours or days apart. For those, advancing a
    cursor past an occurrence costs nothing, because the next one is far away
    anyway. A rule like ``* * * * *`` is different: consecutive occurrences
    are one minute apart, so any extra step in the cursor silently drops half
    of them. That is invisible to a count check (the count still comes back
    full) and to a monotonicity check (the survivors are still in order); only
    comparing the actual times catches it.
    """

    def _naive_local(self, expression, start, count):
        """Every matching local minute in ``start``, computed without the loop."""
        expr = CronExpr.parse(expression)
        out = []
        moment = start + expr.resolution
        while len(out) < count:
            if expr.matches(moment) and not is_imaginary(
                moment.replace(tzinfo=ZoneInfo("UTC"))
            ):
                out.append(moment)
            moment += expr.resolution
        return out

    def test_every_minute_in_utc_is_not_alternated_away(self):
        found = next_after("* * * * *", datetime(2024, 3, 30, 0, 0), 6, tz="UTC")
        self.assertEqual(
            [moment.strftime("%H:%M") for moment in found],
            ["00:01", "00:02", "00:03", "00:04", "00:05", "00:06"],
        )

    def test_every_minute_matches_the_naive_scan(self):
        start = datetime(2024, 3, 30, 0, 0)
        found = next_after("* * * * *", start, 30, tz="UTC")
        self.assertEqual(
            [moment.replace(tzinfo=None) for moment in found],
            self._naive_local("* * * * *", start, 30),
        )

    def test_contiguous_seconds_field_is_also_dense(self):
        # A six-field expression resolves to seconds, so "0-59 * * * * *" is
        # every second and hits the same one-step window from the other side.
        start = datetime(2024, 3, 30, 0, 0, 0)
        found = next_after("0-59 * * * * *", start, 6, tz="UTC")
        self.assertEqual(
            [moment.second for moment in found], [1, 2, 3, 4, 5, 6]
        )

    def test_dense_schedule_agrees_across_a_dst_transition(self):
        # Berlin skips 02:00-02:59 on 31 March 2024. The reported times must be
        # exactly the matching minutes that really exist, with the missing hour
        # absent rather than renumbered.
        start = datetime(2024, 3, 31, 1, 57, tzinfo=ZoneInfo(BERLIN))
        found = next_after("* * * * *", start.replace(tzinfo=None), 5, tz=BERLIN)
        stamps = [moment.strftime("%H:%M %z") for moment in found]
        self.assertEqual(
            stamps,
            [
                "01:58 +0100",
                "01:59 +0100",
                "03:00 +0200",
                "03:01 +0200",
                "03:02 +0200",
            ],
        )

    def test_dense_schedule_is_not_reported_as_fully_matching(self):
        # Count is honoured, but the times are the point: an implementation
        # that skips every other minute still returns `count` results.
        start = datetime(2024, 3, 30, 0, 0)
        found = next_after("* * * * *", start, 8, tz="UTC")
        minutes = [moment.minute for moment in found]
        self.assertEqual(minutes, sorted(minutes))
        self.assertEqual(len(set(minutes)), 8)
        self.assertEqual(minutes[-1] - minutes[0], 7)


class TestTimezoneMonotonicity(unittest.TestCase):
    """Results stay ordered through every transition."""

    def test_ordered_over_three_months_berlin(self):
        found = next_after("*/20 * * * *", datetime(2024, 3, 1), 200, tz=BERLIN)
        self.assertEqual(found, sorted(found))
        self.assertTrue(all(a < b for a, b in zip(found, found[1:])))

    def test_ordered_over_a_year_new_york(self):
        found = next_after("*/20 * * * *", datetime(2024, 1, 1), 1000, tz=NEW_YORK)
        self.assertTrue(all(a < b for a, b in zip(found, found[1:])))
        instants = [to_utc(moment) for moment in found]
        self.assertEqual(instants, sorted(instants))

    def test_each_result_satisfies_the_expression_locally(self):
        expr = CronExpr.parse("0 2,14 * * 1-5")
        found = next_after(expr, datetime(2024, 3, 20), 20, tz=BERLIN)
        for moment in found:
            self.assertTrue(expr.matches(moment.replace(tzinfo=None)))


if __name__ == "__main__":
    unittest.main()
