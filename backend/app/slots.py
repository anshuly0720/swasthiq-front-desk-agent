"""Dates, clock times and the slot grid.

Nothing in this module reads the system clock. Every function that needs to
know what day it is takes `today` as an argument, because the hidden set runs
on a different day than the one this was written on.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .errors import INVALID_ARGUMENTS, INVALID_DATE, INVALID_TIME, ToolError

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# Boundaries for a vague time of day. "subah" is anything before noon, which is
# what makes cv_0001 and cv_0002 land on 09:00.
PARTS_OF_DAY: Dict[str, Tuple[int, int]] = {
    "morning": (0, 12 * 60),
    "afternoon": (12 * 60, 16 * 60),
    "evening": (16 * 60, 24 * 60),
    "any": (0, 24 * 60),
}


def parse_date(value: str, field: str = "date") -> date:
    """Strict YYYY-MM-DD. date.fromisoformat() alone is too permissive on 3.11+."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ToolError(
            INVALID_DATE,
            "{} must be a date in YYYY-MM-DD form, got {!r}".format(field, value),
            field=field,
            expected_format="YYYY-MM-DD",
        )
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolError(
            INVALID_DATE,
            "{} is not a real calendar date: {!r}".format(field, value),
            field=field,
        )


def weekday_of(value: str) -> str:
    """'2026-10-01' -> 'Thu'."""
    return WEEKDAYS[parse_date(value).weekday()]


def shift_days(value: str, days: int) -> str:
    """Relative dates, always against a supplied date — never against now()."""
    return (parse_date(value) + timedelta(days=days)).isoformat()


def parse_hhmm(value: str, field: str = "start") -> int:
    """'09:30' -> 570 minutes past midnight."""
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise ToolError(
            INVALID_TIME,
            "{} must be a 24-hour clock time in HH:MM form, got {!r}".format(
                field, value
            ),
            field=field,
            expected_format="HH:MM",
        )
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def to_hhmm(minutes: int) -> str:
    """570 -> '09:30'."""
    return "{:02d}:{:02d}".format(minutes // 60, minutes % 60)


def part_of_day_bounds(part: str) -> Tuple[int, int]:
    key = (part or "any").strip().lower()
    if key not in PARTS_OF_DAY:
        raise ToolError(
            INVALID_ARGUMENTS,
            "part_of_day must be one of {}, got {!r}".format(
                ", ".join(sorted(PARTS_OF_DAY)), part
            ),
            allowed=sorted(PARTS_OF_DAY),
        )
    return PARTS_OF_DAY[key]


def build_grid(windows: Sequence[Tuple[str, str]], slot_minutes: int) -> List[int]:
    """Start times for one doctor on one weekday, as minutes past midnight.

    The union of the day's windows, de-duplicated and sorted. Dr. Rao's Monday
    windows are 09:00-12:00 and 11:45-15:00: iterating per window yields 25
    starts with 11:45 twice, where the real grid is 24. See DECISIONS.md item 2.
    """
    starts: Set[int] = set()
    for window_start, window_end in windows:
        cursor = parse_hhmm(window_start, "window.start")
        limit = parse_hhmm(window_end, "window.end")
        while cursor + slot_minutes <= limit:
            starts.add(cursor)
            cursor += slot_minutes
    return sorted(starts)


def filter_by_part_of_day(starts: Iterable[str], part: str) -> List[str]:
    low, high = part_of_day_bounds(part)
    return [s for s in starts if low <= parse_hhmm(s) < high]