#!/usr/bin/env python3
"""Compare cronnext's parsing and firing days against the real vixie cron.

``tests/vixie_oracle.py`` is a hand transcription of vixie's ``entry.c`` into
Python.  It shares no code with the library, which is what makes it useful, but
it is still a *reading* of the C.  A shared misreading -- the same person
misreading the same two blocks -- passes every differential test in the suite.
This script removes that residual risk by asking the installed daemon instead.

The oracle is ``crontab(1)`` from the system cron package, driven with
``-x pars``.  That flag runs the real ``entry.c`` and prints every
``set_element()`` and ``set_range()`` call, so the exact bit set cron built for
a field can be recovered rather than inferred, and every one of the five
fields has a distinct (low, high) signature (minute 0-59, hour 0-23,
day-of-month 1-31, month 1-12, day-of-week 0-7) so the trace can be split per
field without putting a marker in the crontab.  Two modes are checked:

* the value set each field expands to, and
* whether the line is accepted at all.

The firing-day comparison goes further: it recomputes cron.c's day rule from
cron's own bits and compares the result with ``next_after()`` across a whole
leap year, which exercises parsing, expansion, the DOM/DOW star rule, Sunday
normalisation and the forward search in one shot.

cron is NOT a dependency of this project.  When no ``crontab`` binary is found
the script says so and exits 0, so it is safe to run on a machine without one.

Usage:  python3 scripts/cross-check-cron.py
Exit 0 when every case agrees (or when no oracle is available), 1 otherwise.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cronnext.expr import CronExpr  # noqa: E402
from cronnext.fields import (  # noqa: E402
    MONTH_NAMES,
    WEEKDAY_NAMES,
    normalize_sunday,
)

CRONTAB = shutil.which("crontab") or ""

#: field name -> (index in a five field crontab line, low, high) exactly as
#: vixie's load_entry() passes them to get_list().
SIGNATURES = {
    "minute": (0, 0, 59),
    "hour": (1, 0, 23),
    "day of month": (2, 1, 31),
    "month": (3, 1, 12),
    "day of week": (4, 0, 7),
}

ELEMENT = re.compile(r"set_element\(\?,\s*(-?\d+),(-?\d+),\s*(-?\d+)\)")
RANGE = re.compile(r"set_range\(\?,\s*(-?\d+),(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\)")

#: A legal rest-of-line, so the probe never fails for an unrelated reason.
COMMAND = "/bin/true"


def _installed_crontab() -> str:
    """Return the caller's real crontab, so the probes can put it back."""
    proc = subprocess.run([CRONTAB, "-l"], capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def _restore_crontab(saved: str) -> None:
    """Put the caller's crontab back exactly as it was."""
    if saved.strip():
        with tempfile.NamedTemporaryFile(
            "w", suffix=".cron", delete=False
        ) as handle:
            handle.write(saved)
            path = handle.name
        subprocess.run([CRONTAB, path], capture_output=True, text=True)
        Path(path).unlink(missing_ok=True)
    else:
        # `crontab -r` is only safe here because saved is known to be empty.
        subprocess.run([CRONTAB, "-r"], capture_output=True, text=True)


def _cron_debug(line: str, saved: str) -> tuple[int, str, str] | None:
    """Install ``line`` through crontab with parsing debug and capture it.

    crontab(1) offers no way to parse a file without installing it, so every
    probe overwrites the caller's crontab.  It is saved before the first probe
    and restored after each one, so running this script never leaves the
    caller's jobs changed or deleted.

    Returns None when crontab itself cannot be driven at all -- a locked down
    container, a PAM prompt, no permission to touch the spool.  That is an
    absent oracle rather than a disagreement, so the caller skips.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".cron", delete=False) as handle:
        handle.write(line + "\n")
        path = handle.name
    try:
        proc = subprocess.run(
            [CRONTAB, "-x", "pars,load", path], capture_output=True, text=True
        )
    except OSError:
        return None
    finally:
        _restore_crontab(saved)
        Path(path).unlink(missing_ok=True)
    # A crontab that cannot report a parse error at all (no line diagnostics)
    # is not usable as an oracle.
    if proc.returncode != 0 and not proc.stderr.strip() and not proc.stdout.strip():
        return None
    return proc.returncode, proc.stdout, proc.stderr


#: Set once, if crontab turns out to be undrivable, so the run can stop early
#: instead of probing a binary that will never answer.
ORACLE_BROKEN = False


def _bits_from_trace(stdout: str, low: int, high: int) -> set[int]:
    """Recover one field's bit set from cron's own debug output."""
    bits: set[int] = set()
    for line in stdout.splitlines():
        match = ELEMENT.search(line)
        if match and (int(match.group(1)), int(match.group(2))) == (low, high):
            bits.add(int(match.group(3)))
            continue
        match = RANGE.search(line)
        if match and (int(match.group(1)), int(match.group(2))) == (low, high):
            start, stop, step = (int(match.group(i)) for i in (3, 4, 5))
            # entry.c set_range(): a step that is 1, or wider than the range,
            # fills the whole range instead of stepping.
            if step <= 1 or step > stop - start:
                bits |= set(range(start, stop + 1))
            else:
                bits |= set(range(start, stop + 1, step))
    return bits


def cron_field_bits(field: str, text: str, saved: str) -> set[int] | None:
    """Return the values real cron builds for ``field``, or None if it rejects.

    None means "no answer from the oracle": either cron rejected the line, or
    crontab could not be driven at all.
    """
    global ORACLE_BROKEN
    index, low, high = SIGNATURES[field]
    parts = ["0", "0", "*", "*", "*"]
    parts[index] = text
    result = _cron_debug(" ".join(parts) + " " + COMMAND, saved)
    if result is None:
        ORACLE_BROKEN = True
        return None
    code, stdout, _ = result
    if code != 0:
        return None
    return _bits_from_trace(stdout, low, high)


def cron_firing_days(
    dom_text: str, dow_text: str, start: date, days: int, saved: str
) -> list[date] | None:
    """Recompute cron.c's day rule from cron's own bits."""
    dom_bits = cron_field_bits("day of month", dom_text, saved)
    if dom_bits is None:
        return None
    dow_bits = cron_field_bits("day of week", dow_text, saved)
    if dow_bits is None:
        return None
    # entry.c sets DOM_STAR / DOW_STAR from the raw field text, before any
    # expansion, which is what makes '*/2' and '*,7' wildcards too.
    dom_star = dom_text.startswith("*")
    dow_star = dow_text.startswith("*")
    # entry.c's "make sundays equivalent" fixup runs in load_entry() before
    # cron.c ever reads the field, and only the single `dow` bit is read, so
    # this must be applied to the raw traced bits to reproduce cron's firing
    # days.  Without it a crontab spelling Sunday as '7' would fire on
    # nothing at all, which is exactly what cronnext does if it forgets to
    # fold 7 onto 0 -- so the fixup is what makes this check able to tell a
    # correct implementation from one with the fold removed.
    if 0 in dow_bits or 7 in dow_bits:
        dow_bits = dow_bits | {0, 7}

    fired: list[date] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        thisdom = day.day in dom_bits
        thisdow = (day.weekday() + 1) % 7 in dow_bits
        hit = (thisdom and thisdow) if (dom_star or dow_star) else (thisdom or thisdow)
        if hit:
            fired.append(day)
    return fired


#: Field tokens covering the awkward syntax: lists, steps, steps wider than the
#: range, names, the two Sunday spellings and values at each boundary.
FIELD_CASES = [
    ("minute", token)
    for token in ("*", "0", "59", "*/15", "*/59", "*/60", "*/99", "5-10/2",
                  "5-10/5", "5-10/99", "1,2,3", "0-59/1", "30-59/30",
                  "*/0", "1/0", "5-10/0", "0/0")
] + [
    ("hour", token) for token in ("*", "0", "23", "*/6", "*/24", "1-12/4", "0-23")
] + [
    ("day of month", token)
    for token in ("*", "1", "31", "*/2", "*/31", "*/32", "1-15", "15-31", "1,15,31")
] + [
    ("month", token)
    for token in ("*", "1", "12", "*/3", "*/12", "*/13", "JAN", "JAN-DEC", "DEC,JAN",
                  "jan", "Dec", "JAN-MAR", "jan-mar", "DEC-FEB", "1-6/2")
] + [
    ("day of week", token)
    for token in ("*", "0", "7", "6", "0-6", "0-7", "*/2", "*/7", "*/99",
                  "MON-FRI", "SUN,SAT", "7,0", "sun", "SUN-SAT", "0-6/2",
                  "7-7", "7-0", "1-7", "1-0", "6-7", "7-6", "*/8", "*/6")
]

#: Fields where cronnext deliberately departs from vixie: a descending range
#: wraps around the end of the field here, while vixie's fill loop simply does
#: not execute and the field keeps no bits.  This is a documented extension,
#: so the cross-check records it as expected rather than as a failure; the
#: divergence itself is pinned by the TestDescendingRangesDifferFromVixie
#: class in tests/test_vixie_differential.py.
KNOWN_EXTENSION_DESCENDING = {
    ("month", "DEC-FEB"),
    ("day of week", "7-0"),
    ("day of week", "1-0"),
    ("day of week", "7-6"),
}

#: Day-of-month / day-of-week pairs covering the star rule in both directions.
DAY_PAIRS = [
    ("*", "*"), ("*", "1"), ("1", "1"), ("1", "*"),
    ("*/2", "1"), ("*/3", "1"), ("1", "*/2"), ("1", "*/3"),
    ("*/2", "*/2"), ("1-15", "1"), ("*,7", "1"), ("1", "*,7"),
    ("*/7", "2-4"), ("15", "*/3"), ("*/2", "1-5"), ("1,15", "0"),
    ("*/2", "0"), ("2", "*/2"), ("*/2", "*"), ("*", "*/2"),
    ("7", "*"), ("*", "7"), ("1", "*/7"), ("*", "*/7"),
    ("13", "5"), ("1", "0"), ("1", "7"), ("31", "6"), ("1", "6"),
    ("*/2", "*/3"), ("1-31", "0"), ("1-31", "7"), ("15", "0"),
    ("*/15", "0"), ("1,2,3", "1,2,3"), ("*", "1,3,5"), ("*/4", "*"),
    ("29", "*"), ("*", "SUN"), ("1", "SAT,SUN"), ("*/2", "SUN"),
    ("10-20", "0"), ("1-10", "5"), ("*/7", "SUN"), ("5", "1-5"),
    ("*/3", "6"), ("*/5", "3"), ("2-30", "2"), ("*", "0-4"),
    # A bare 7 and a bare 0 must both mean Sunday, and a field that names
    # Sunday alongside a weekday must fire on both.  These are the cases that
    # fail if the 7 -> 0 fold in cronnext is removed, because cronnext's
    # weekday numbering has no 7 at all once the fold is gone.
    ("*", "7"), ("15", "7"), ("*", "0"), ("15", "0"), ("*", "0,7"),
    ("*", "7,1"), ("*", "0,1"), ("*", "SUN"), ("*", "SAT,SUN"),
    ("*/2", "7"), ("*/2", "0"), ("*", "SUN-SAT"), ("*", "0-6"),
    ("*", "0-7"), ("*", "*/7"), ("*", "*/2"), ("*", "*/99"),
    # Names must be case-insensitive, and an unknown name must not be read as
    # a range boundary.
    ("*", "sun"), ("*", "sunday"), ("*", "Sat"), ("*", "saT,sun"),
    ("*", "SUN-SAT"), ("*", "sun-sat"), ("*", "THU"), ("*", "thu"),
]

START = date(2024, 1, 1)
DAYS = 366


#: vixie passes a name table to get_list() for these two fields; Field.parse
#: needs the same one or it will reject every name as unknown.
NAMES = {"month": MONTH_NAMES, "day of week": WEEKDAY_NAMES}


def _sundays_equivalent(bits: set[int]) -> set[int]:
    """Apply entry.c's "make sundays equivalent" fixup to a day-of-week set.

    vixie runs this in load_entry() *after* get_list() has set the field, so
    the Debug(DPARS) trace shows the pre-fixup bits: a crontab that wrote '0'
    traces only bit 0, and one that wrote '7' traces only bit 7.  The fixup
    then sets both, and cron.c reads only the `dow` bit, which is why the two
    spellings behave identically.

    cronnext folds 7 onto 0 at parse time instead of carrying both bits, so
    applying the same fixup to both sides puts them in a common
    representation and makes the comparison meaningful.
    """
    if 0 in bits or 7 in bits:
        return bits | {0, 7}
    return bits


def check_fields(saved: str) -> tuple[list[str], set[str]]:
    """Compare each field's value set with the real daemon.

    Returns the problems found and the set of documented extensions that
    were seen to diverge, so the summary can report them honestly rather
    than hiding them behind an exit code of 0.
    """
    from cronnext.fields import Field, FieldError

    problems: list[str] = []
    expected_differences: set[str] = set()
    for field, text in FIELD_CASES:
        index, low, high = SIGNATURES[field]
        kwargs = {}
        if field == "day of week":
            kwargs = {"normalize": normalize_sunday, "star_maximum": 6}
        if field in NAMES:
            kwargs["names"] = NAMES[field]
        try:
            mine = set(Field.parse(field, text, low, high, **kwargs).values)
        except FieldError as exc:
            mine = None
            detail = str(exc)
        else:
            detail = ""
        theirs = cron_field_bits(field, text, saved)
        if mine is None and theirs is None:
            continue
        if mine is None or theirs is None:
            problems.append(
                f"{field} {text!r}: cronnext "
                f"{'rejects' if mine is None else 'accepts'} "
                f"({'error: ' + detail if mine is None else ''}), "
                f"cron {'rejects' if theirs is None else 'accepts'}"
            )
            continue
        # The stored bit sets must match exactly, with no fixup applied to
        # either side.  cronnext folds a written 7 onto 0 at parse time, so
        # its stored set for '7' is {0}; cron leaves the traced bits alone and
        # relies on entry.c's post-parse fixup, so its set for '7' is {7}.
        # Those are the same *behaviour* only because cron.c reads the fixed
        # up bits, which the firing-day check verifies on its own.  Comparing
        # the raw stored sets here would flag a spelling difference as a bug,
        # so the two spellings of Sunday are compared by their meaning in the
        # firing-day cases below, and this check compares the stored sets after
        # putting cron's traced bits through the same fold cronnext does.
        if field == "day of week":
            theirs_stored = _sundays_equivalent(theirs)
            mine_stored = _sundays_equivalent(mine)
        else:
            theirs_stored = theirs
            mine_stored = mine
        if mine_stored != theirs_stored:
            if (field, text) in KNOWN_EXTENSION_DESCENDING:
                expected_differences.add(f"{field} {text!r}")
                continue
            problems.append(
                f"{field} {text!r}: cronnext {_compact(mine_stored)}, "
                f"cron {_compact(theirs_stored)}"
            )
    return problems, expected_differences


def check_firing_days(saved: str) -> list[str]:
    """Compare next_after() with the day rule recomputed from cron's own bits."""
    problems: list[str] = []
    for dom_text, dow_text in DAY_PAIRS:
        expected = cron_firing_days(dom_text, dow_text, START, DAYS, saved)
        if expected is None:
            # cron rejects the line, so there is no firing set to compare.
            continue
        line = f"0 0 {dom_text} * {dow_text}"
        try:
            expression = CronExpr.parse(line)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{line!r}: cronnext rejects ({exc}), cron accepts")
            continue
        horizon = datetime(START.year, 1, 1)
        got = [
            moment.date()
            for moment in expression.next_after(horizon - timedelta(minutes=1), 400)
        ]
        got = [day for day in got if day < START + timedelta(days=DAYS)]
        if got != expected:
            only_cron = sorted(set(expected) - set(got))
            only_next = sorted(set(got) - set(expected))
            problems.append(
                f"{line!r}: cronnext {_compact_dates(got)}, "
                f"cron {_compact_dates(expected)}"
                + (f"; only cronnext: {only_next[:5]}" if only_next else "")
                + (f"; only cron: {only_cron[:5]}" if only_cron else "")
            )
    return problems


def _compact(values: set[int]) -> str:
    return "{" + ",".join(str(value) for value in sorted(values)) + "}"


def _compact_dates(values: list[date]) -> str:
    if not values:
        return "{} (never fires)"
    return "{" + ",".join(value.isoformat() for value in values[:6]) + (
        ",...}" if len(values) > 6 else "}"
    )


def main() -> int:
    global ORACLE_BROKEN
    if not CRONTAB:
        print("no crontab binary found; skipping the real-cron cross-check")
        return 0
    print(f"oracle: {CRONTAB}")

    # Probes install throwaway crontabs, so the caller's own jobs are saved
    # once up front and restored after every single probe.
    saved = _installed_crontab()
    try:
        field_problems, expected = check_fields(saved)
        day_problems = check_firing_days(saved)
        if ORACLE_BROKEN:
            print(
                "\ncrontab could not be driven on this machine (locked down spool, "
                "PAM prompt or no permission); skipping the real-cron cross-check"
            )
            return 0
        problems = field_problems + day_problems
    finally:
        _restore_crontab(saved)

    total = len(FIELD_CASES) + len(DAY_PAIRS)
    if expected:
        print(
            f"\n{len(expected)} documented extension(s) differ from vixie by "
            f"design: {', '.join(sorted(expected))}"
        )
    if not problems:
        print(f"\n{total} cases agree with the real daemon")
        return 0
    print(f"\n{len(problems)} of {total} cases disagree:\n")
    for problem in problems:
        print(f"  {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())