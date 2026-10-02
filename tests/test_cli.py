"""End-to-end tests for the cronnext command line interface."""

import contextlib
import io
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from cronnext.cli import EXIT_HORIZON, EXIT_OK, EXIT_USAGE, main  # noqa: E402


def run_cli(*args):
    """Run the CLI in a subprocess and return the CompletedProcess.

    Running out of process is the point: it proves the module entry point,
    the exit codes and the printed output work as a user would see them.
    """
    environment = dict(os.environ)
    environment["PYTHONPATH"] = ROOT
    return subprocess.run(
        [sys.executable, "-m", "cronnext.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )


class TestCommandLineOutput(unittest.TestCase):
    """The default output is one ISO timestamp per line."""

    def test_quarter_hourly(self):
        result = run_cli("*/15 * * * *", "-n", "5", "--from", "2024-01-01T00:07:00")
        self.assertEqual(result.returncode, EXIT_OK)
        self.assertEqual(
            result.stdout.strip().splitlines(),
            [
                "2024-01-01T00:15:00+00:00",
                "2024-01-01T00:30:00+00:00",
                "2024-01-01T00:45:00+00:00",
                "2024-01-01T01:00:00+00:00",
                "2024-01-01T01:15:00+00:00",
            ],
        )

    def test_weekday_three(self):
        result = run_cli("0 3 * * 1-5", "-n", "5", "--from", "2024-01-05T12:00:00")
        self.assertEqual(result.returncode, EXIT_OK)
        self.assertEqual(
            result.stdout.strip().splitlines(),
            [
                "2024-01-08T03:00:00+00:00",
                "2024-01-09T03:00:00+00:00",
                "2024-01-10T03:00:00+00:00",
                "2024-01-11T03:00:00+00:00",
                "2024-01-12T03:00:00+00:00",
            ],
        )

    def test_default_count_is_five(self):
        result = run_cli("0 0 * * *", "--from", "2024-01-01T00:00:00")
        self.assertEqual(len(result.stdout.strip().splitlines()), 5)

    def test_count_one(self):
        result = run_cli("0 0 * * *", "-n", "1", "--from", "2024-01-01T00:00:00")
        self.assertEqual(result.stdout.strip(), "2024-01-02T00:00:00+00:00")

    def test_timezone_option(self):
        result = run_cli(
            "0 3 * * 1-5", "-n", "1", "--from", "2024-01-05T12:00:00", "--tz", "Europe/Berlin"
        )
        self.assertEqual(result.stdout.strip(), "2024-01-08T03:00:00+01:00")

    def test_from_accepts_z_suffix(self):
        result = run_cli("0 0 * * *", "-n", "1", "--from", "2024-01-01T00:00:00Z")
        self.assertEqual(result.stdout.strip(), "2024-01-02T00:00:00+00:00")

    def test_from_accepts_space_separator(self):
        result = run_cli("0 0 * * *", "-n", "1", "--from", "2024-01-01 00:00:00")
        self.assertEqual(result.stdout.strip(), "2024-01-02T00:00:00+00:00")

    def test_alias_on_the_command_line(self):
        result = run_cli("@daily", "-n", "2", "--from", "2024-01-01T06:00:00")
        self.assertEqual(
            result.stdout.strip().splitlines(),
            ["2024-01-02T00:00:00+00:00", "2024-01-03T00:00:00+00:00"],
        )

    def test_six_field_expression(self):
        result = run_cli("*/30 * * * * *", "-n", "4", "--from", "2024-01-01T00:00:00")
        self.assertEqual(
            result.stdout.strip().splitlines(),
            [
                "2024-01-01T00:00:30+00:00",
                "2024-01-01T00:01:00+00:00",
                "2024-01-01T00:01:30+00:00",
                "2024-01-01T00:02:00+00:00",
            ],
        )

    def test_no_from_uses_now_and_succeeds(self):
        result = run_cli("0 0 * * *", "-n", "1")
        self.assertEqual(result.returncode, EXIT_OK)
        self.assertEqual(len(result.stdout.strip().splitlines()), 1)

    def test_expression_with_spaces_is_one_argument(self):
        result = run_cli("0  0   *  *  *", "-n", "1", "--from", "2024-01-01T05:00:00")
        self.assertEqual(result.returncode, EXIT_OK)
        self.assertEqual(result.stdout.strip(), "2024-01-02T00:00:00+00:00")


class TestCommandLineTable(unittest.TestCase):
    """--table prints aligned columns."""

    def test_table_has_a_underline_row(self):
        result = run_cli("0 0 * * *", "-n", "3", "--from", "2024-01-01T00:00:00", "--table")
        lines = result.stdout.strip().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("---", lines[1])

    def test_table_columns_align(self):
        result = run_cli("0 0 * * *", "-n", "3", "--from", "2024-01-01T00:00:00", "--table")
        lines = result.stdout.strip().splitlines()
        rule = lines[1]
        self.assertNotIn(" ", rule.replace("  ", ""))
        self.assertRegex(rule, r"^-+(  -+)+$")
        # Every data row has the local time column padded to the same width,
        # so the ISO timestamp column starts at one offset throughout.
        starts = {line.index("+00:00") for line in lines[::2]}
        self.assertEqual(len(starts), 1)

    def test_table_contains_iso_timestamp(self):
        result = run_cli("0 0 * * *", "-n", "1", "--from", "2024-01-01T00:00:00", "--table")
        self.assertIn("2024-01-02T00:00:00+00:00", result.stdout)


class TestCommandLineErrors(unittest.TestCase):
    """Exit codes: 0 ok, 2 usage or parse error, 3 horizon exhausted."""

    def test_invalid_expression_exits_two(self):
        result = run_cli("not a cron", "-n", "1")
        self.assertEqual(result.returncode, EXIT_USAGE)
        self.assertIn("invalid expression", result.stderr)

    def test_out_of_range_field_exits_two(self):
        result = run_cli("99 * * * *")
        self.assertEqual(result.returncode, EXIT_USAGE)

    def test_unknown_alias_exits_two(self):
        result = run_cli("@fortnightly")
        self.assertEqual(result.returncode, EXIT_USAGE)

    def test_unknown_timezone_exits_two(self):
        result = run_cli("0 0 * * *", "--tz", "Mars/Olympus")
        self.assertEqual(result.returncode, EXIT_USAGE)
        self.assertIn("unknown timezone", result.stderr)

    def test_bad_from_value_exits_two(self):
        result = run_cli("0 0 * * *", "--from", "not-a-date")
        self.assertEqual(result.returncode, EXIT_USAGE)
        self.assertIn("--from", result.stderr)

    def test_missing_expression_exits_two(self):
        result = run_cli()
        self.assertEqual(result.returncode, EXIT_USAGE)

    def test_negative_count_exits_two(self):
        result = run_cli("0 0 * * *", "-n", "-1")
        self.assertEqual(result.returncode, EXIT_USAGE)

    def test_zero_count_succeeds_with_no_output(self):
        result = run_cli("0 0 * * *", "-n", "0")
        self.assertEqual(result.returncode, EXIT_OK)
        self.assertEqual(result.stdout.strip(), "")

    def test_horizon_exhausted_exits_three(self):
        result = run_cli("0 0 29 2 *", "-n", "1", "--from", "2025-01-01T00:00:00",
                         "--horizon-years", "2")
        self.assertEqual(result.returncode, EXIT_HORIZON)
        self.assertIn("within 2 years", result.stderr)

    def test_horizon_exhausted_still_prints_what_exists(self):
        result = run_cli("0 0 29 2 *", "-n", "2", "--from", "2025-01-01T00:00:00",
                         "--horizon-years", "3")
        self.assertEqual(result.returncode, EXIT_HORIZON)
        self.assertEqual(
            result.stdout.strip().splitlines(), ["2028-02-29T00:00:00+00:00"]
        )

    def test_short_horizon_flag_exits_three(self):
        # The horizon is start.year + years, so a one year horizon from
        # December 2024 ends at December 2025 and only a handful of yearly
        # runs fit: asking for five runs of 1 January cannot be satisfied.
        result = run_cli("0 0 1 1 *", "-n", "5", "--from", "2024-12-31T00:00:00",
                         "--horizon-years", "1")
        self.assertEqual(result.returncode, EXIT_HORIZON)
        self.assertIn("within 1 years", result.stderr)
        self.assertEqual(
            result.stdout.strip().splitlines(), ["2025-01-01T00:00:00+00:00"]
        )


class TestCommandLineHelp(unittest.TestCase):
    """--help and --version."""

    def test_help_exits_zero(self):
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("EXPR", result.stdout)
        self.assertIn("--tz", result.stdout)
        self.assertIn("--from", result.stdout)
        self.assertIn("--table", result.stdout)

    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("0.1.0", result.stdout)

    def test_help_documents_exit_status(self):
        result = run_cli("--help")
        self.assertIn("Exit status", result.stdout)


class TestMainCallable(unittest.TestCase):
    """main() called in process, for its return value.

    stdout and stderr are captured so the test runner's own output stays
    readable.
    """

    def setUp(self):
        self._capture_target = io.StringIO()
        self._error_target = io.StringIO()
        self._capture = contextlib.redirect_stdout(self._capture_target)
        self._error_capture = contextlib.redirect_stderr(self._error_target)
        self._capture.__enter__()
        self._error_capture.__enter__()
        self.addCleanup(self._capture.__exit__, None, None, None)
        self.addCleanup(self._error_capture.__exit__, None, None, None)

    def test_main_returns_zero(self):
        self.assertEqual(
            main(["0 0 * * *", "-n", "1", "--from", "2024-01-01T00:00:00"]), EXIT_OK
        )

    def test_main_returns_two_on_bad_expression(self):
        self.assertEqual(main(["bad expr here now"]), EXIT_USAGE)

    def test_main_returns_two_on_bad_timezone(self):
        self.assertEqual(main(["0 0 * * *", "--tz", "Bad/Zone"]), EXIT_USAGE)

    def test_main_returns_three_on_empty_horizon(self):
        self.assertEqual(
            main(["0 0 30 2 *", "-n", "1", "--from", "2024-01-01T00:00:00"]),
            EXIT_HORIZON,
        )

    def test_main_prints_iso_lines(self):
        main(["0 0 * * *", "-n", "2", "--from", "2024-01-01T00:00:00"])
        printed = self._capture_target.getvalue().strip().splitlines()
        self.assertEqual(
            printed, ["2024-01-02T00:00:00+00:00", "2024-01-03T00:00:00+00:00"]
        )

    def test_exit_constants(self):
        self.assertEqual((EXIT_OK, EXIT_USAGE, EXIT_HORIZON), (0, 2, 3))


if __name__ == "__main__":
    unittest.main()
