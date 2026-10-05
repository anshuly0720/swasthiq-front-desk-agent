from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from ..slots import WEEKDAYS, parse_date, to_hhmm

WEEKDAY_WORDS: Dict[str, int] = {
    "somwar": 0, "somvar": 0, "monday": 0, "mon": 0,
    "mangalwar": 1, "mangalvar": 1, "tuesday": 1, "tue": 1,
    "budhwar": 2, "budhvar": 2, "budhavar": 2, "wednesday": 2, "wed": 2,
    "guruwar": 3, "guruvar": 3, "brihaspativar": 3, "veerwar": 3, "thursday": 3, "thu": 3,
    "shukrawar": 4, "shukravar": 4, "friday": 4, "fri": 4,
    "shaniwar": 5, "shanivar": 5, "shanivaar": 5, "saturday": 5, "sat": 5,
    "raviwar": 6, "ravivar": 6, "itwar": 6, "itvar": 6, "sunday": 6, "sun": 6,
}
RELATIVE_DAY_WORDS: Dict[str, int] = {
    "aaj": 0, "aj": 0, "today": 0,
    "kal": 1, "tomorrow": 1, "kl": 1,
    "parso": 2, "parson": 2, "narso": 3,
}
HINDI_NUMBERS: Dict[str, int] = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "chah": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "gyaarah": 11, "egarah": 11, "barah": 12, "baarah": 12,
}
PART_WORDS = {
    "morning": ("subah", "subeh", "savere", "morning", "am"),
    "afternoon": ("dopahar", "dupahar", "afternoon", "noon"),
    "evening": ("shaam", "sham", "evening", "pm"),
}
_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")

# Built by concatenation, never str.format: a {1,2} quantifier inside a format
# string is read as a replacement field and raises KeyError at import time.
_DAY_TAREEKH = re.compile(r"\b(\d{1,2})\s*(?:tareekh|tarikh|tarik|taarikh)\b")
_DAY_ORDINAL = re.compile(r"\b(\d{1,2})\s*(?:st|nd|rd|th)\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})\s+(?:" + "|".join(_MONTHS) + r")\b")
_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_CLOCK = re.compile(r"\b(\d{1,2})[:.](\d{2})\b")
_BARE_NUMBER = re.compile(r"\b(\d{1,2})\b")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _word(w: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(w) + r"\b")


def resolve_date(expression: str, today: str) -> Optional[Dict[str, object]]:
    """Resolve a date phrase against the request's `today`.

    Returns {date, basis, conflict} or None. `conflict` is set when the phrase
    names both a weekday and a day number that disagree -- "Shukravar 3 tareekh"
    when the 3rd is a Saturday. Picking a half is the kind of invention this
    assignment is about, so the disagreement is surfaced, not resolved.
    """
    text = _normalise(expression)
    if not text:
        return None

    base = parse_date(today, "today")
    found: List[Tuple[str, date]] = []

    iso = _ISO.search(text)
    if iso:
        try:
            found.append(("iso", parse_date(iso.group(1))))
        except Exception:  # noqa: BLE001 - a malformed ISO string is simply not a date
            pass

    # "Kal ya parso" means parso: the last option offered is the one meant.
    relative = None
    for word, offset in RELATIVE_DAY_WORDS.items():
        match = _word(word).search(text)
        if match and (relative is None or match.start() > relative[0]):
            relative = (match.start(), offset)
    if relative is not None:
        found.append(("relative", base + timedelta(days=relative[1])))

    match = _DAY_TAREEKH.search(text) or _DAY_ORDINAL.search(text) or _DAY_MONTH.search(text)
    if match:
        day_number = int(match.group(1))
        if 1 <= day_number <= 31:
            resolved = _next_with_day_number(base, day_number)
            if resolved:
                found.append(("day_number", resolved))

    weekday_target = None
    for word, index in WEEKDAY_WORDS.items():
        if _word(word).search(text):
            weekday_target = index
            found.append(("weekday", _next_weekday(base, index)))
            break

    if not found:
        return None

    # An explicit day number beats everything else: it is the least ambiguous
    # thing a caller can say. A weekday that disagrees is reported, not used.
    priority = ["iso", "day_number", "weekday", "relative"]
    found.sort(key=lambda pair: priority.index(pair[0]))
    basis, chosen = found[0]

    conflict = None
    if weekday_target is not None and basis in ("iso", "day_number"):
        if chosen.weekday() != weekday_target:
            conflict = "caller said {} but {} is a {}".format(
                WEEKDAYS[weekday_target], chosen.isoformat(), WEEKDAYS[chosen.weekday()])

    return {"date": chosen.isoformat(), "basis": basis, "conflict": conflict}


def _next_weekday(base: date, weekday: int) -> date:
    """Next occurrence, today included: "Saturday" said on Saturday is today."""
    return base + timedelta(days=(weekday - base.weekday()) % 7)


def _next_with_day_number(base: date, day_number: int) -> Optional[date]:
    for month_offset in range(0, 3):
        year = base.year + (base.month - 1 + month_offset) // 12
        month = (base.month - 1 + month_offset) % 12 + 1
        try:
            candidate = date(year, month, day_number)
        except ValueError:
            continue
        if candidate >= base:
            return candidate
    return None


def resolve_time(expression: str, part_of_day: Optional[str] = None) -> Optional[str]:
    """"gyarah baje" -> 11:00. "saadhe das" -> 10:30. "9:30" -> 09:30."""
    text = _normalise(expression)
    if not text:
        return None

    quarter = 0
    if re.search(r"\b(saadhe|sadhe|sade)\b", text):
        quarter = 30
    elif re.search(r"\b(sawa|sava)\b", text):
        quarter = 15
    elif re.search(r"\b(paune|pone)\b", text):
        quarter = -15

    hour = minute = None
    clock = _CLOCK.search(text)
    if clock:
        hour, minute = int(clock.group(1)), int(clock.group(2))
    else:
        digits = _BARE_NUMBER.search(text)
        if digits:
            hour, minute = int(digits.group(1)), 0
        else:
            for word, value in HINDI_NUMBERS.items():
                if _word(word).search(text):
                    hour, minute = value, 0
                    break
    if hour is None or hour > 23:
        return None

    # "paune gyarah" is a quarter TO eleven, not eleven.
    total = hour * 60 - 15 if quarter == -15 else hour * 60 + minute + quarter

    part = part_of_day or detect_part_of_day(text)
    if hour < 12 and part == "evening":
        total += 12 * 60
    elif hour == 12 and part == "morning":
        total -= 12 * 60
    elif part is None and 1 <= hour <= 7 and not re.search(r"\bam\b", text):
        # The clinic runs 09:00-20:00, so a bare "5 baje" is the evening.
        total += 12 * 60

    return to_hhmm(total % (24 * 60))


def detect_part_of_day(text: str) -> Optional[str]:
    lowered = _normalise(text)
    for part, words in PART_WORDS.items():
        for word in words:
            if _word(word).search(lowered):
                return part
    return None