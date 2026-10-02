"""Command line interface for cronnext."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import List, Optional, Sequence

from . import __version__
from .expr import MAX_HORIZON_YEARS, CronError, CronExpr
from .next import TimezoneError, next_after as timezone_next_after

__all__ = ["build_parser", "main"]

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_HORIZON = 3


def _parse_start(text: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 ``--from`` value into a datetime.

    Args:
        text: The text to parse, or None for "now".

    Returns:
        The parsed datetime, naive unless the text carried an offset.

    Raises:
        ValueError: If the text is not a valid ISO 8601 datetime.
    """
    if text is None:
        return None
    candidate = text.strip()
    if not candidate:
        raise ValueError("empty --from value")
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    return datetime.fromisoformat(candidate)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser used by :func:`main`."""
    parser = argparse.ArgumentParser(
        prog="cronnext",
        description=(
            "Print the next fire times of a standard 5-field crontab "
            "expression. An optional 6th leading seconds field is supported, "
            "as are the @yearly .. @hourly aliases."
        ),
        epilog=(
            "Exit status: 0 on success, 2 for a usage or parse error, "
            f"3 when fewer than the requested number of occurrences exist "
            f"within {MAX_HORIZON_YEARS} years."
        ),
    )
    parser.add_argument("expression", metavar="EXPR", help="the crontab expression")
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=5,
        metavar="N",
        help="number of occurrences to print (default: 5)",
    )
    parser.add_argument(
        "--tz",
        default=None,
        metavar="ZONE",
        help="IANA timezone, e.g. Europe/Berlin (default: UTC; 'local' uses the system zone)",
    )
    parser.add_argument(
        "--from",
        dest="start",
        default=None,
        metavar="ISO8601",
        help="search from this ISO 8601 datetime instead of now",
    )
    parser.add_argument(
        "--table",
        action="store_true",
        help="print aligned columns with the local time and UTC offset",
    )
    parser.add_argument(
        "--horizon-years",
        type=int,
        default=MAX_HORIZON_YEARS,
        metavar="Y",
        help=(
            f"search bound in years past the start (default: {MAX_HORIZON_YEARS})"
        ),
    )
    parser.add_argument("--version", action="version", version=f"cronnext {__version__}")
    return parser


def _format_table(rows: Sequence[str]) -> List[str]:
    """Return ``rows`` laid out as a column table with a dashed rule.

    Each input row is split on whitespace into cells; every column but the
    last is padded to a common width so the rows line up.  A dashed rule
    follows the first row.
    """
    if not rows:
        return []
    cells = [row.split() for row in rows]
    widths = [
        max(len(row[column]) for row in cells) for column in range(max(len(r) for r in cells))
    ]
    lines: List[str] = []
    for index, row in enumerate(cells):
        padded = [
            cell.ljust(widths[position]) if position < len(row) - 1 else cell
            for position, cell in enumerate(row)
        ]
        lines.append("  ".join(padded).rstrip())
        if index == 0:
            rule = "  ".join("-" * width for width in widths)
            lines.append(rule)
    return lines


def _resolve_zone(name: Optional[str]) -> Optional[str]:
    """Map the ``local`` keyword onto the system timezone name.

    Args:
        name: The ``--tz`` value, None, or ``"local"``.

    Returns:
        An IANA timezone name, or None for UTC.
    """
    if name is None:
        return None
    if name == "local":
        current = datetime.now().astimezone().tzinfo
        return getattr(current, "key", None) or "UTC"
    return name


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the command line interface.

    Args:
        argv: Argument list, defaulting to :data:`sys.argv` minus the
            program name.

    Returns:
        0 on success, 2 on a usage or parse error, 3 when the requested
        number of occurrences does not exist within the horizon.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.count < 0:
        parser.error("--count must not be negative")
    if args.horizon_years < 1:
        parser.error("--horizon-years must be at least 1")

    try:
        expression = CronExpr.parse(args.expression)
    except CronError as error:
        print(f"cronnext: invalid expression: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        start = _parse_start(args.start)
    except ValueError as error:
        print(f"cronnext: invalid --from value: {error}", file=sys.stderr)
        return EXIT_USAGE

    if start is None:
        start = datetime.now().astimezone().replace(tzinfo=None)

    try:
        found = timezone_next_after(
            expression,
            start,
            args.count,
            tz=_resolve_zone(args.tz),
            horizon_years=args.horizon_years,
        )
    except TimezoneError as error:
        print(f"cronnext: {error}", file=sys.stderr)
        return EXIT_USAGE

    if args.table:
        rows = []
        for moment in found:
            local = moment.strftime("%Y-%m-%d %H:%M:%S %Z")
            rows.append(f"{local} {moment.isoformat()}")
        output = _format_table(rows)
    else:
        output = [moment.isoformat() for moment in found]
    for line in output:
        print(line)

    if len(found) < args.count:
        print(
            f"cronnext: only {len(found)} of {args.count} occurrences exist "
            f"within {args.horizon_years} years",
            file=sys.stderr,
        )
        return EXIT_HORIZON
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
