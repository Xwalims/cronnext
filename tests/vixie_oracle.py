"""An independent port of vixie-cron's day matching, for differential testing.

Nothing here imports :mod:`cronnext`.  The wildcard flags and the combination
rule are transcribed from the C source, so that a test can compare the two
implementations and catch a shared-assumption bug that a self-consistent
reference (such as :mod:`tests.naive`) structurally cannot.

Transcribed from vixie/cron, with the same two checks in cronie/cron:

``entry.c`` -- the wildcard flags come from the raw field text, before any
range is expanded, because the parser tests ``ch == '*'`` on the field's first
character::

    if (ch == '*')
            e->flags |= DOM_STAR;      /* and DOW_STAR for the day of week */

``cron.c`` ``find_jobs()`` -- one rule, with a single bit tested for the
weekday::

    dow = now.tm_wday - FIRST_DOW;
    ...
    ((e->flags & (DOM_STAR|DOW_STAR)) != 0)
         ? (thisdom && thisdow)
         : (thisdom || thisdow)

``entry.c`` also makes the two spellings of Sunday equivalent::

    /* make sundays equivalent */
    if (bit_test(e->dow, 0) || bit_test(e->dow, 7)) {
            bit_set(e->dow, 0);
            bit_set(e->dow, 7);
    }

Because only bit ``dow`` is ever tested, both bits must be set for a bare
``7`` to fire on Sunday, which is exactly what that block guarantees.
"""

__all__ = ["vixie_day_matches", "vixie_accepts"]

#: Day-of-month runs 1..31; day-of-week runs 0..7 with 0 and 7 both Sunday.
_DOM_MIN, _DOM_MAX = 1, 31
_DOW_MIN, _DOW_MAX = 0, 7


def _expand_item(item, low_limit, high_limit):
    """Expand one list item, or return None when vixie would reject it.

    A descending range such as ``5-1`` is *not* a syntax error in vixie, and
    vixie does not wrap it either.  Upstream ``get_range()`` fills the field
    with ``for (i = num1; i <= num2; i += num3)``, which simply does not
    execute when ``num1 > num2``, so the field ends up with no bits set.  The
    entry still parses; the job just never fires.  Debian's 3.0pl1 keeps the
    same loop and adds only an out-of-bounds check around it, so it behaves
    identically here.

    Returning an empty set rather than None encodes exactly that: the range is
    accepted and matches nothing.
    """
    step = 1
    body = item
    if "/" in item:
        body, step_text = item.split("/", 1)
        if not step_text.isdigit():
            return None
        step = int(step_text)
        if step < 1:
            return None
    if body == "*":
        low, high = low_limit, high_limit
    elif "-" in body:
        low_text, _, high_text = body.partition("-")
        if not low_text.isdigit() or not high_text.isdigit():
            return None
        low, high = int(low_text), int(high_text)
    else:
        if not body.isdigit():
            return None
        low = int(body)
        # ``a/n``: upstream stops at the single value ``a``; the
        # ``a-<maximum>/n`` reading is a cronnext extension.
        high = high_limit if step > 1 else low
    if low < low_limit or high > high_limit:
        return None
    if low > high:
        return set()
    return {
        low + offset
        for offset in range(0, high - low + 1, step)
        if low + offset <= high_limit
    }


def _expand(field_text, low_limit, high_limit):
    """Expand a whole field, or return None when vixie would reject it.

    An empty set is a real answer, not a rejection: vixie accepts a field whose
    items set no bits and the job then never fires.
    """
    values = set()
    for item in field_text.split(","):
        if not item:
            return None
        expanded = _expand_item(item, low_limit, high_limit)
        if expanded is None:
            return None
        values |= expanded
    return values


def vixie_accepts(dom_text, dow_text):
    """Return True when vixie-cron would accept this pair of day fields."""
    return (
        _expand(dom_text, _DOM_MIN, _DOM_MAX) is not None
        and _expand(dow_text, _DOW_MIN, _DOW_MAX) is not None
    )


def vixie_day_matches(dom_text, dow_text, day, weekday):
    """Return True when vixie-cron fires on this day.

    Args:
        dom_text: The day-of-month field exactly as written in the crontab.
        dow_text: The day-of-week field exactly as written.
        day: Day of the month, 1..31.
        weekday: Day of the week in vixie's numbering, Sunday is 0.

    Returns:
        The day decision made by the transcribed C code.
    """
    dom_bits = _expand(dom_text, _DOM_MIN, _DOM_MAX) or set()
    dow_bits = _expand(dow_text, _DOW_MIN, _DOW_MAX) or set()

    # entry.c: the wildcard flags come from the raw text, before expansion.
    dom_star = dom_text.startswith("*")
    dow_star = dow_text.startswith("*")

    thisdom = day in dom_bits
    # Only the single bit `dow` is tested, so both Sunday bits must be set.
    thisdow = weekday in dow_bits
    if 0 in dow_bits or 7 in dow_bits:
        thisdow = weekday in (dow_bits | {0, 7})

    if dom_star or dow_star:
        return thisdom and thisdow
    return thisdom or thisdow