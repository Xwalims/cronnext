# cronnext

Compute the next fire times of a standard crontab expression, with correct
vixie-cron semantics, a timezone aware library API and a command line tool.
Pure standard library, no dependencies.

## What it is

`cronnext` answers one question: when does this crontab line next run?

```console
$ cronnext '*/15 * * * *' --from 2026-03-02T09:07:00
2026-03-02T09:15:00+00:00
2026-03-02T09:30:00+00:00
2026-03-02T09:45:00+00:00
2026-03-02T10:00:00+00:00
2026-03-02T10:15:00+00:00
```

It is aimed at scheduling code, dashboards and deployment tooling that need
to preview or explain a schedule rather than run it. It parses the crontab
syntax properly, including the parts that surprise people, and it reports
real timestamps in whatever timezone you ask for.

## Semantics implemented

### Field syntax

Each field is a comma separated list of items. An item is one of:

| Form | Meaning |
| --- | --- |
| `*` | every value in the field |
| `a` | the single value `a` |
| `a-b` | the inclusive range `a` to `b` |
| `*/n` | every `n`-th value across the field |
| `a-b/n` | every `n`-th value within the range |
| `a/n` | vixie-cron shorthand for `a-<maximum>/n` |

A range whose lower bound is above its upper bound wraps around the end of
the field, exactly as vixie-cron does. `5-1` in the day-of-week field is
Friday, Saturday, Sunday, Monday. When such a wrapped range carries a step,
the step is applied to the wrapped sequence, so `5-1/2` is Friday and Sunday.

Month names `JAN` through `DEC` and weekday names `SUN` through `SAT` are
accepted wherever a number is accepted, in any case. In the day-of-week
field both `0` and `7` mean Sunday and are normalised to `0`.

### Day-of-month and day-of-week combine with OR

This is the rule that catches people out. When **both** the day-of-month and
the day-of-week fields are restricted, a day matches when **either one**
matches. `0 0 13 * FRI` runs on every Friday *and* on the 13th of every
month, not only on days that are both.

When one of the two fields is a bare `*`, only the other field is consulted,
which means `0 0 1 * 0` (the first of the month, or any Sunday) really does
fire on every Sunday of the month.

A field counts as "restricted" only when it is written as something other
than a bare `*`. `*/2` is restricted; `*` is not.

### Seconds field

An optional sixth, leading field adds seconds resolution, as supported by
several modern crontab implementations. `*/30 * * * * *` means every 30
seconds, and the whole field set shifts: seconds, minute, hour, day of
month, month, day of week.

### Aliases

The standard nicknames are supported and expand exactly as in vixie-cron.

## Supported fields

| Field | Range | Accepted extras |
| --- | --- | --- |
| seconds | `0-59` | only in the 6-field form, as the leading field |
| minute | `0-59` | |
| hour | `0-23` | |
| day of month | `1-31` | |
| month | `1-12` | names `JAN`-`DEC` |
| day of week | `0-6`, with `7` also Sunday | names `SUN`-`SAT` |

Out-of-range values are rejected at parse time with an error that names the
offending field, so `60 * * * *` fails immediately instead of quietly
producing nothing.

## Aliases table

| Alias | Expands to |
| --- | --- |
| `@yearly` | `0 0 1 1 *` |
| `@annually` | `0 0 1 1 *` |
| `@monthly` | `0 0 1 * *` |
| `@weekly` | `0 0 * * 0` |
| `@daily` | `0 0 * * *` |
| `@midnight` | `0 0 * * *` |
| `@hourly` | `0 * * * *` |

## Install

```console
$ python3 -m pip install .
```

The package requires Python 3.11 or newer and has no dependencies. It can
also be run straight from a checkout without installing:

```console
$ python3 -m cronnext.cli '0 3 * * 1-5' --from 2026-03-02T09:07:00
2026-03-03T03:00:00+00:00
2026-03-04T03:00:00+00:00
2026-03-05T03:00:00+00:00
2026-03-06T03:00:00+00:00
2026-03-09T03:00:00+00:00
```

## Usage

```
cronnext EXPR [-n N] [--tz ZONE] [--from ISO8601] [--table] [--horizon-years Y]
```

| Option | Meaning |
| --- | --- |
| `-n`, `--count N` | number of occurrences to print, default 5 |
| `--tz ZONE` | IANA timezone name, default UTC; `local` uses the system zone |
| `--from ISO8601` | search from this datetime instead of the current time |
| `--table` | print aligned columns with the local time and zone abbreviation |
| `--horizon-years Y` | search bound in years past the start, default 8 |

### Default output

One ISO 8601 timestamp per line, in the requested timezone, including the
UTC offset.

```console
$ cronnext '*/15 * * * *' --from 2026-03-02T09:07:00
2026-03-02T09:15:00+00:00
2026-03-02T09:30:00+00:00
2026-03-02T09:45:00+00:00
2026-03-02T10:00:00+00:00
2026-03-02T10:15:00+00:00
```

### Weekdays only

```console
$ cronnext '0 3 * * 1-5' --from 2026-03-02T09:07:00
2026-03-03T03:00:00+00:00
2026-03-04T03:00:00+00:00
2026-03-05T03:00:00+00:00
2026-03-06T03:00:00+00:00
2026-03-09T03:00:00+00:00
```

The jump from Friday 6 March to Monday 9 March is the weekend being skipped.

### Timezone and table output

```console
$ cronnext '0 2 30 * *' -n 3 --tz Europe/Berlin --from 2026-03-02T09:07:00 --table
2026-03-30  02:00:00  CEST  2026-03-30T02:00:00+02:00
----------  --------  ----  -------------------------
2026-04-30  02:00:00  CEST  2026-04-30T02:00:00+02:00
2026-05-30  02:00:00  CEST  2026-05-30T02:00:00+02:00
```

### Sparse schedules

```console
$ cronnext '0 0 29 2 *' -n 1 --from 2026-03-02T09:07:00
2028-02-29T00:00:00+00:00
```

### Exit status

| Code | Meaning |
| --- | --- |
| 0 | success |
| 2 | usage or parse error: bad expression, bad `--from`, unknown timezone |
| 3 | fewer than the requested number of occurrences exist within the horizon |

On exit code 3 the occurrences that do exist are still printed, and a note
goes to standard error.

```console
$ cronnext '0 0 1 1 *' -n 5 --from 2024-12-31T00:00:00 --horizon-years 1
2025-01-01T00:00:00+00:00
cronnext: only 1 of 5 occurrences exist within 1 years
$ echo $?
3
```

### The search horizon

The search is bounded to eight years past the starting year by default. That
bound is generous enough to cover the worst gap in the calendar: the longest
wait between two occurrences of `0 0 29 2 *` is eight years, from 29
February 2096 to 29 February 2104, because 2100 is not a leap year. The
bound is what makes expressions that can never fire, such as `0 0 30 2 *`,
terminate immediately with no results instead of walking the calendar to the
year 10000. Lower it with `--horizon-years`.

The search is also fast. Instead of stepping a minute at a time, it skips
forward over time that cannot possibly match: to the next matching minute, to
the next matching hour at `:00`, to the next day at `00:00`, or to the first
of the next matching month. The test suite asserts that this optimised
search returns exactly the same results as a naive minute-by-minute scan
across a fixed window, for every expression it covers.

## Timezone behaviour

`next_after` returns timezone aware datetimes. The expression always matches
**local wall clock time** in the zone you pass, which is what a cron
daemon does.

- A naive `datetime` argument is read as local time in that zone.
- An aware `datetime` argument is converted into that zone first, then used.
- `tz=None` means UTC. Pass `--tz local` on the command line for the system
  zone.

Daylight saving has two awkward cases, and `cronnext` resolves both the way a
wall clock scheduler must.

**Non-existent local times are skipped.** On a spring-forward morning the
clock jumps from 02:00 to 03:00, so 02:30 never happens on that day.
`cronnext` emits nothing for it and moves on to the next local time that
really exists. It does not shift the job to 04:30: a job scheduled for 02:30
should not silently run at a different hour.

```console
$ cronnext '30 2 * * *' -n 3 --tz Europe/Berlin --from 2024-03-29T12:00:00
2024-03-30T02:30:00+01:00
2024-04-01T02:30:00+02:00
2024-04-02T02:30:00+02:00
```

31 March is missing entirely, because 02:30 does not exist that morning in
Berlin.

**Ambiguous local times run once.** On an autumn evening the clock repeats an
hour, so the same local time occurs twice. `cronnext` reports it a single
time, at `fold=0`, which is the first pass through the clock.

```console
$ cronnext '30 2 * * *' -n 2 --tz Europe/Berlin --from 2024-10-26T12:00:00
2024-10-27T02:30:00+02:00
2024-10-28T02:30:00+01:00
```

27 October appears once, at the summer offset, even though 02:30 happens
twice that night.

Results are strictly increasing both as local wall clock times and as
absolute instants, across every transition.

## Library API

```python
from datetime import datetime
from cronnext import CronExpr, next_after

# Timezone aware search.
next_after("*/15 * * * *", datetime(2024, 1, 1, 0, 7), 5, tz="Europe/Berlin")

# The wall clock search, which takes a naive datetime and returns naive
# results. This is the pure calendar calculation with no zone attached.
expr = CronExpr.parse("0 3 * * 1-5")
expr.next_after(datetime(2024, 1, 5, 12, 0), 5)
```

| Name | Purpose |
| --- | --- |
| `CronExpr.parse(text)` | parse an expression; raises `CronError` |
| `CronExpr.matches(moment)` | does this wall clock moment match |
| `CronExpr.day_matches(moment)` | the day-of-month / day-of-week rule alone |
| `CronExpr.next_after(after, count)` | naive search, one resolution step at a time |
| `next_after(expr, after, count, tz)` | timezone aware search, handles DST |
| `Field.parse(name, text, min, max)` | parse a single field |
| `cron_dow(moment)` | weekday number with Sunday as 0 |
| `to_utc(moment)` | convert to UTC, assuming UTC when naive |

Errors are specific: `CronError` for a whole expression, `FieldError` for a
single field, `TimezoneError` for an unknown zone, and `ValueError` for a
negative count or an impossible argument.

## Running the tests

The suite is stdlib `unittest`, so no test runner needs to be installed.

```console
$ python3 -m unittest discover -s tests -t . -v
```

Run it from the project root. It covers field parsing for every syntax form
and every rejection, the day-of-month / day-of-week rule in both directions,
the seconds field, all seven aliases, calendar boundaries including leap
days and year rollover, monotonicity of every returned sequence, the
daylight saving cases above, the equivalence of the fast search with a naive
scan, and the command line interface end to end in a subprocess.

## License

MIT. See [LICENSE](LICENSE).
