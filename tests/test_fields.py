"""Tests for :mod:`cronnext.fields`."""

import unittest

from cronnext.fields import (
    MONTH_NAMES,
    WEEKDAY_NAMES,
    Field,
    FieldError,
    normalize_sunday,
)


def minute_field(text):
    """Parse ``text`` as a minute field."""
    return Field.parse("minute", text, 0, 59)


def month_field(text):
    """Parse ``text`` as a month field with names enabled."""
    return Field.parse("month", text, 1, 12, names=MONTH_NAMES)


def dow_field(text):
    """Parse ``text`` as a day-of-week field with names and folding."""
    return Field.parse(
        "day of week",
        text,
        0,
        7,
        names=WEEKDAY_NAMES,
        normalize=normalize_sunday,
        star_maximum=6,
    )


class TestWildcardAndSingle(unittest.TestCase):
    """The two simplest item forms."""

    def test_star_covers_whole_range(self):
        self.assertEqual(minute_field("*").sorted_values(), tuple(range(60)))

    def test_star_sets_star_flag(self):
        self.assertTrue(minute_field("*").star)

    def test_single_value(self):
        self.assertEqual(minute_field("7").sorted_values(), (7,))

    def test_single_value_is_not_star(self):
        self.assertFalse(minute_field("7").star)

    def test_zero_is_a_valid_minute(self):
        self.assertEqual(minute_field("0").sorted_values(), (0,))

    def test_contains_helper(self):
        field = minute_field("5,10")
        self.assertTrue(field.contains(10))
        self.assertFalse(field.contains(11))

    def test_in_operator(self):
        self.assertIn(5, minute_field("5"))
        self.assertNotIn(6, minute_field("5"))

    def test_in_operator_rejects_non_int(self):
        self.assertNotIn("5", minute_field("5"))

    def test_text_is_preserved(self):
        self.assertEqual(minute_field(" 1,2 ").text, "1,2")

    def test_str_round_trip(self):
        self.assertEqual(str(minute_field("*/5")), "*/5")


class TestLists(unittest.TestCase):
    """Comma separated lists."""

    def test_two_element_list(self):
        self.assertEqual(minute_field("1,2").sorted_values(), (1, 2))

    def test_unsorted_list(self):
        self.assertEqual(minute_field("30,10,20").sorted_values(), (10, 20, 30))

    def test_duplicates_collapse(self):
        self.assertEqual(minute_field("5,5,5").sorted_values(), (5,))

    def test_list_mixed_with_star(self):
        self.assertEqual(minute_field("*,7").sorted_values(), tuple(range(60)))

    def test_list_with_leading_star_is_a_wildcard(self):
        # vixie-cron entry.c tests ``ch == '*'`` on the field's first
        # character before it ever looks at the rest of the list, so a field
        # that merely *starts* with a star is a wildcard even though its
        # expanded values are narrowed by the extra items.
        self.assertTrue(minute_field("*,7").star)
        self.assertTrue(minute_field("*/2").star)
        self.assertTrue(minute_field("*,7,9").star)

    def test_long_list(self):
        self.assertEqual(len(minute_field("1,3,5,7,9,11").values), 6)

    def test_empty_list_element_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("1,,2")

    def test_trailing_comma_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("1,2,")

    def test_empty_text_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("")


class TestRanges(unittest.TestCase):
    """Ranges, including wraparound."""

    def test_simple_range(self):
        self.assertEqual(minute_field("10-13").sorted_values(), (10, 11, 12, 13))

    def test_range_spanning_zero(self):
        self.assertEqual(dow_field("5-1").sorted_values(), (0, 1, 5, 6))

    def test_wraparound_range_dow_sat_to_mon(self):
        self.assertEqual(dow_field("6-1").sorted_values(), (0, 1, 6))

    def test_wraparound_range_dow_fri_to_wed(self):
        self.assertEqual(dow_field("5-3").sorted_values(), (0, 1, 2, 3, 5, 6))

    def test_wraparound_month_nov_to_feb(self):
        self.assertEqual(month_field("11-2").sorted_values(), (1, 2, 11, 12))

    def test_equal_bounds_is_single_value(self):
        self.assertEqual(minute_field("9-9").sorted_values(), (9,))

    def test_incomplete_range_start_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("-5")

    def test_incomplete_range_end_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("5-")

    def test_reversed_range_with_three_parts_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("1-2-3")

    def test_range_lower_bound_out_of_range(self):
        with self.assertRaises(FieldError):
            Field.parse("hour", "24-25", 0, 23)

    def test_range_upper_bound_out_of_range(self):
        with self.assertRaises(FieldError):
            Field.parse("hour", "0-24", 0, 23)


class TestSteps(unittest.TestCase):
    """The ``/`` step operator in every accepted form."""

    def test_star_step(self):
        self.assertEqual(minute_field("*/15").sorted_values(), (0, 15, 30, 45))

    def test_star_step_of_one_is_whole_range(self):
        self.assertEqual(minute_field("*/1").sorted_values(), tuple(range(60)))

    def test_step_from_value_extends_to_maximum(self):
        self.assertEqual(minute_field("50/5").sorted_values(), (50, 55))

    def test_range_with_step(self):
        self.assertEqual(minute_field("0-10/2").sorted_values(), (0, 2, 4, 6, 8, 10))

    def test_range_with_step_not_dividing_evenly(self):
        self.assertEqual(minute_field("0-9/3").sorted_values(), (0, 3, 6, 9))

    def test_hour_step(self):
        self.assertEqual(Field.parse("hour", "*/6", 0, 23).sorted_values(), (0, 6, 12, 18))

    def test_wraparound_range_with_step(self):
        # 5-1 wraps to the sequence 5, 6, 0, 1; stepping by two from the
        # start of that sequence keeps 5 and 0.
        self.assertEqual(dow_field("5-1/2").sorted_values(), (0, 5))

    def test_wraparound_range_with_step_of_one(self):
        self.assertEqual(dow_field("5-1/1").sorted_values(), (0, 1, 5, 6))

    def test_wraparound_month_range_with_step(self):
        # 11-2 wraps to 11, 12, 1, 2; stepping by two keeps 11 and 1.
        self.assertEqual(month_field("11-2/2").sorted_values(), (1, 11))

    def test_step_below_one_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("*/0")

    def test_negative_step_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("*/-1")

    def test_non_numeric_step_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("*/x")

    def test_two_slashes_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("*/2/3")

    def test_empty_step_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("*/")

    def test_step_larger_than_range(self):
        self.assertEqual(minute_field("*/90").sorted_values(), (0,))


class TestNames(unittest.TestCase):
    """Month and weekday names."""

    def test_month_names_all_resolve(self):
        for name, number in MONTH_NAMES.items():
            self.assertEqual(month_field(name).sorted_values(), (number,))

    def test_month_name_lowercase(self):
        self.assertEqual(month_field("jan").sorted_values(), (1,))

    def test_month_name_mixed_case(self):
        self.assertEqual(month_field("DeC").sorted_values(), (12,))

    def test_month_name_in_range(self):
        self.assertEqual(month_field("jan-mar").sorted_values(), (1, 2, 3))

    def test_month_name_in_list(self):
        self.assertEqual(month_field("JAN,Jun,dec").sorted_values(), (1, 6, 12))

    def test_unknown_month_name_rejected(self):
        with self.assertRaises(FieldError):
            month_field("janu")

    def test_weekday_names_all_resolve(self):
        for name, number in WEEKDAY_NAMES.items():
            self.assertEqual(dow_field(name).sorted_values(), (number,))

    def test_weekday_name_range(self):
        self.assertEqual(dow_field("mon-fri").sorted_values(), (1, 2, 3, 4, 5))

    def test_unknown_weekday_name_rejected(self):
        with self.assertRaises(FieldError):
            dow_field("funday")

    def test_names_rejected_when_not_allowed(self):
        with self.assertRaises(FieldError):
            minute_field("mon")

    def test_name_in_minute_field_rejected(self):
        with self.assertRaises(FieldError):
            Field.parse("day of month", "15-foo", 1, 31)


class TestWeekdayFolding(unittest.TestCase):
    """Both 0 and 7 mean Sunday."""

    def test_zero_is_sunday(self):
        self.assertEqual(dow_field("0").sorted_values(), (0,))

    def test_seven_is_sunday(self):
        self.assertEqual(dow_field("7").sorted_values(), (0,))

    def test_seven_and_zero_in_one_list_deduplicate(self):
        self.assertEqual(dow_field("0,7").sorted_values(), (0,))

    def test_full_range_collapses_to_seven_values(self):
        self.assertEqual(len(dow_field("*").values), 7)

    def test_saturday_is_six(self):
        self.assertEqual(dow_field("SAT").sorted_values(), (6,))

    def test_wraparound_covers_sunday_once(self):
        self.assertEqual(len(dow_field("6-0").values), 2)

    def test_normalize_sunday_helper(self):
        self.assertEqual(normalize_sunday(7), 0)
        self.assertEqual(normalize_sunday(0), 0)
        self.assertEqual(normalize_sunday(3), 3)


class TestOutOfRange(unittest.TestCase):
    """Every field rejects values outside its own bounds."""

    def test_minute_too_large(self):
        with self.assertRaises(FieldError):
            minute_field("60")

    def test_hour_too_large(self):
        with self.assertRaises(FieldError):
            Field.parse("hour", "24", 0, 23)

    def test_day_of_month_zero_rejected(self):
        with self.assertRaises(FieldError):
            Field.parse("day of month", "0", 1, 31)

    def test_day_of_month_32_rejected(self):
        with self.assertRaises(FieldError):
            Field.parse("day of month", "32", 1, 31)

    def test_month_zero_rejected(self):
        with self.assertRaises(FieldError):
            month_field("0")

    def test_month_13_rejected(self):
        with self.assertRaises(FieldError):
            month_field("13")

    def test_day_of_week_8_rejected(self):
        with self.assertRaises(FieldError):
            dow_field("8")

    def test_seconds_60_rejected(self):
        with self.assertRaises(FieldError):
            Field.parse("seconds", "60", 0, 59)

    def test_negative_value_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("-1")

    def test_non_numeric_value_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("abc")

    def test_error_message_mentions_field_name(self):
        with self.assertRaises(FieldError) as caught:
            minute_field("60")
        self.assertIn("minute", str(caught.exception))


class TestHelpers(unittest.TestCase):
    """first, next_after and sorted_values."""

    def test_first(self):
        self.assertEqual(minute_field("20,5,10").first(), 5)

    def test_next_after_value(self):
        field = minute_field("*/15")
        self.assertEqual(field.next_after(0), 15)
        self.assertEqual(field.next_after(15), 30)

    def test_next_after_past_end_returns_none(self):
        self.assertIsNone(minute_field("0-10").next_after(50))

    def test_next_after_keeps_type(self):
        self.assertIsInstance(minute_field("*").next_after(3), int)

    def test_values_are_frozenset(self):
        self.assertIsInstance(minute_field("*").values, frozenset)

    def test_whitespace_inside_field_rejected(self):
        with self.assertRaises(FieldError):
            minute_field("1 2")


if __name__ == "__main__":
    unittest.main()
