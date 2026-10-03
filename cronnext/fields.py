"""Parsing of a single crontab field.

A :class:`Field` holds the normalised set of values that one whitespace
separated token of a crontab line may take.  Parsing follows vixie-cron: a
field is a comma separated list of items, every item is one of

``*``
    the whole range of the field, written ``low-high`` internally
``a``
    a single value
``a-b``
    an inclusive range; when ``a > b`` the range wraps around the end of the
    field (``5-2`` in the day-of-week field is Fri, Sat, Sun, Mon)
``*/n``
    the whole range restricted to every ``n``-th value
``a-b/n``
    a range restricted to every ``n``-th value
``a/n``
    vixie-cron shorthand for ``a-<maximum>/n``

Month names (``JAN``..``DEC``) and weekday names (``SUN``..``SAT``) are
accepted wherever a number is accepted, case-insensitively.  In the
day-of-week field both ``0`` and ``7`` denote Sunday; they are normalised to
``0``.  Every produced :class:`Field` reports ``star=True`` when its text
begins with ``*``, which is what the day-of-month / day-of-week rule in
:mod:`cronnext.expr` needs: vixie-cron's parser tests the field's first
character before it expands anything, so ``*/2`` and ``*,7`` are wildcards
as well.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, Optional, Tuple

__all__ = [
    "Field",
    "FieldError",
    "MONTH_NAMES",
    "WEEKDAY_NAMES",
]


class FieldError(ValueError):
    """Raised when a crontab field cannot be parsed."""


#: Month names, 1-based, as accepted in the month field.
MONTH_NAMES: Dict[str, int] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

#: Weekday names; Sunday is 0 and Saturday is 6.
WEEKDAY_NAMES: Dict[str, int] = {
    "SUN": 0,
    "MON": 1,
    "TUE": 2,
    "WED": 3,
    "THU": 4,
    "FRI": 5,
    "SAT": 6,
}


def normalize_sunday(value: int) -> int:
    """Map day-of-week ``7`` onto ``0``; every other value passes through."""
    return 0 if value == 7 else value


@dataclass(frozen=True)
class Field:
    """One parsed crontab field.

    Attributes:
        name: Human readable field name, used in error messages.
        minimum: Smallest legal value of the field.
        maximum: Largest legal value of the field.
        values: Normalised frozenset of accepted values.
        star: True when the field text begins with ``*``.
        text: The original field text, stripped.
    """

    name: str
    minimum: int
    maximum: int
    values: FrozenSet[int]
    star: bool
    text: str

    # -- construction ----------------------------------------------------

    @classmethod
    def parse(
        cls,
        name: str,
        text: str,
        minimum: int,
        maximum: int,
        names: Optional[Dict[str, int]] = None,
        normalize: Optional[Callable[[int], int]] = None,
        star_maximum: Optional[int] = None,
    ) -> "Field":
        """Parse ``text`` into a :class:`Field`.

        Args:
            name: Field name used in error messages, e.g. ``"minute"``.
            text: The field text, e.g. ``"*/15"``.
            minimum: Smallest legal value.
            maximum: Largest legal value that may be written literally.  The
                day-of-week field passes 7 here so that both spellings of
                Sunday parse.
            names: Optional mapping of upper-case names to values.
            normalize: Optional callable applied to every parsed value, used
                to fold day-of-week ``7`` onto ``0``.
            star_maximum: Upper bound used when expanding a bare ``*``,
                defaulting to ``maximum``.  The day-of-week field passes 6
                so that ``*`` means seven days, not eight.

        Returns:
            The parsed :class:`Field`.

        Raises:
            FieldError: If the text is empty, malformed or out of range.
        """
        raw = text.strip()
        if not raw:
            raise FieldError(f"{name} field is empty")
        if any(character.isspace() for character in raw):
            raise FieldError(f"{name} field {text!r} contains whitespace")

        if star_maximum is None:
            star_maximum = maximum

        values: set[int] = set()
        for item in raw.split(","):
            if not item:
                raise FieldError(f"{name} field {text!r} has an empty list element")
            values |= cls._parse_item(
                name, item, minimum, maximum, names, star_maximum
            )

        # vixie-cron decides "this field is a wildcard" from the raw text,
        # before any list expansion: entry.c tests ``ch == '*'`` on the first
        # character of the field and sets DOM_STAR / DOW_STAR accordingly.
        # That makes ``*/2`` and ``*,7`` wildcards too, which matters because
        # cron.c switches the day-of-month / day-of-week rule to AND as soon
        # as either flag is set.
        star = raw.startswith("*")

        if not values:
            raise FieldError(f"{name} field {text!r} matches no values")
        if normalize is not None:
            values = {normalize(value) for value in values}

        return cls(
            name=name,
            minimum=minimum,
            maximum=maximum,
            values=frozenset(values),
            star=star,
            text=raw,
        )

    @classmethod
    def _parse_item(
        cls,
        name: str,
        item: str,
        minimum: int,
        maximum: int,
        names: Optional[Dict[str, int]],
        star_maximum: int,
    ) -> set[int]:
        """Parse one comma separated item into its values."""
        body = item
        step = 1
        if "/" in item:
            pieces = item.split("/")
            if len(pieces) != 2:
                raise FieldError(f"{name} field item {item!r} has more than one '/'")
            body, step_text = pieces
            step = cls._parse_step(name, item, step_text)

        if body == "*":
            low, high = minimum, star_maximum
        elif "-" in body:
            if body.startswith("-") or body.endswith("-"):
                raise FieldError(f"{name} field item {item!r} has an incomplete range")
            low_text, high_text = body.split("-", 1)
            if "-" in high_text:
                raise FieldError(
                    f"{name} field item {item!r} has more than one '-'"
                )
            low = cls._parse_value(name, item, low_text, minimum, maximum, names)
            high = cls._parse_value(name, item, high_text, minimum, maximum, names)
        else:
            low = cls._parse_value(name, item, body, minimum, maximum, names)
            # ``a/n`` is vixie-cron shorthand for ``a-<maximum>/n``.
            high = star_maximum if step > 1 else low

        return cls._expand(name, item, low, high, step, minimum, star_maximum)

    @staticmethod
    def _parse_step(name: str, item: str, step_text: str) -> int:
        if not step_text.isdigit():
            raise FieldError(f"{name} field item {item!r} has a non-numeric step")
        step = int(step_text)
        if step < 1:
            raise FieldError(f"{name} field item {item!r} has a step below 1")
        return step

    @staticmethod
    def _parse_value(
        name: str,
        item: str,
        text: str,
        minimum: int,
        maximum: int,
        names: Optional[Dict[str, int]],
    ) -> int:
        if not text:
            raise FieldError(f"{name} field item {item!r} has a missing value")
        if not text.isdigit():
            if names is None:
                raise FieldError(f"{name} field item {item!r} may not use names")
            resolved = names.get(text.upper())
            if resolved is None:
                raise FieldError(f"{name} field item {item!r} has unknown name {text!r}")
            return resolved
        value = int(text)
        if value < minimum or value > maximum:
            raise FieldError(
                f"{name} field item {item!r} is out of range "
                f"{minimum}-{maximum}: {value}"
            )
        return value

    @staticmethod
    def _expand(
        name: str,
        item: str,
        low: int,
        high: int,
        step: int,
        minimum: int,
        star_maximum: int,
    ) -> set[int]:
        """Expand ``low..high`` by ``step``; a descending range wraps around.

        ``5-2`` in the day-of-week field means Fri, Sat, Sun, Mon: the range
        climbs from ``low`` to the end of the field and then continues at
        ``minimum`` up to ``high``.
        """
        if low <= high:
            offsets = range(0, high - low + 1, step)
        else:
            # low itself, then every value up to star_maximum, then every
            # value from minimum up to and including high.
            offsets = range(0, (star_maximum - low) + (high - minimum) + 2, step)
        span = star_maximum - minimum + 1
        return {(low + offset - minimum) % span + minimum for offset in offsets}

    # -- queries ---------------------------------------------------------

    def contains(self, value: int) -> bool:
        """Return True when ``value`` is one of the field's values."""
        return value in self.values

    def sorted_values(self) -> Tuple[int, ...]:
        """Return every accepted value in ascending order."""
        return tuple(sorted(self.values))

    def first(self) -> int:
        """Return the smallest accepted value."""
        return min(self.values)

    def next_after(self, value: int) -> Optional[int]:
        """Return the smallest accepted value greater than ``value``.

        Returns:
            The next value, or None when every value is ``<= value``.
        """
        greater = [candidate for candidate in self.values if candidate > value]
        return min(greater) if greater else None

    def __contains__(self, value: object) -> bool:
        if not isinstance(value, int):
            return False
        return value in self.values

    def __str__(self) -> str:
        return self.text
