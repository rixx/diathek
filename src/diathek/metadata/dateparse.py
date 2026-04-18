"""Liberally-parsed date input for the slide-tagging UI.

Pure-Python, no Django imports. Import-safe in management commands and tests.
Accepts english and german variants on equal footing. See PLAN.md "date input"
for the required coverage matrix.
"""

from __future__ import annotations

import dataclasses
import datetime
import re


class ParseError(ValueError):
    """Raised when input cannot be interpreted as a date."""


EXACT = "exact"
MONTH = "month"
SEASON = "season"
YEAR = "year"
RANGE = "range"
DECADE = "decade"
UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True)
class ParsedDate:
    earliest: datetime.date
    latest: datetime.date
    precision: str
    display: str


MONTHS = {
    "jan": 1, "january": 1, "januar": 1,
    "feb": 2, "february": 2, "februar": 2,
    "mar": 3, "march": 3, "mär": 3, "märz": 3,
    "apr": 4, "april": 4,
    "may": 5, "mai": 5,
    "jun": 6, "june": 6, "juni": 6,
    "jul": 7, "july": 7, "juli": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "okt": 10, "oktober": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12, "dez": 12, "dezember": 12,
}  # fmt: skip

# Northern hemisphere month ranges. Winter spans into the following year.
SEASONS = {
    "spring": (3, 5, False),
    "frühling": (3, 5, False),
    "summer": (6, 8, False),
    "sommer": (6, 8, False),
    "autumn": (9, 11, False),
    "fall": (9, 11, False),
    "herbst": (9, 11, False),
    "winter": (12, 2, True),
}

_DECADE_MODS = {
    "early": "early", "frühe": "early", "früh": "early", "anfang": "early",
    "mid": "mid", "mitte": "mid",
    "late": "late", "späte": "late", "spät": "late", "ende": "late",
}  # fmt: skip

# Suggestion tokens exposed for the startswith-style input autocomplete.
MONTH_SUGGESTIONS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)  # fmt: skip
SEASON_SUGGESTIONS = ("Frühling", "Sommer", "Herbst", "Winter")
FUZZY_SUGGESTIONS = ("ca. ", "etwa ", "Anfang ", "Mitte ", "Ende ")


_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_SEASON_ALT = "|".join(sorted(SEASONS, key=len, reverse=True))
_Y = r"(?:\d{4}|\d{2})"

_RE_EXACT_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_RE_EXACT_DE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_RE_MONTH_ISO = re.compile(r"^(\d{4})-(\d{1,2})$")
_RE_MONTH_NUM = re.compile(rf"^(\d{{1,2}})[./]({_Y})$")
_RE_MONTH_NAME = re.compile(rf"^({_MONTH_ALT})\.?[ ./_-]+({_Y})$")
_RE_SEASON = re.compile(rf"^({_SEASON_ALT})\s+({_Y})$")
_RE_DECADE_MOD = re.compile(
    rf"^(late|early|mid|späte?|ende|frühe?|mitte|anfang)\s+({_Y})(?:s|er)$"
)
_RE_DECADE = re.compile(rf"^({_Y})(?:s|er)$")
_RE_FUZZY = re.compile(rf"^(?:~|ca\.?|circa|etwa|around|approximately)\s*({_Y})$")
_RE_RANGE = re.compile(rf"^({_Y})\s*(?:[-–—]|bis|to)\s*({_Y})$")
_RE_YEAR = re.compile(rf"^({_Y})$")


def _collapse_whitespace(text):
    return re.sub(r"\s+", " ", text.strip())


def _expand_year(digits, reference=None):
    if len(digits) == 4:
        return int(digits)
    if reference is not None:
        century = (reference // 100) * 100
        return century + int(digits)
    return 1900 + int(digits)


def _end_of_month(year, month):
    if month == 12:
        return datetime.date(year, 12, 31)
    return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)


def parse(text):
    if text is None:
        raise ParseError("Leerer Datumstext.")
    display = text
    raw = text.strip()
    if raw == "":
        raise ParseError("Leerer Datumstext.")
    norm = _collapse_whitespace(raw).lower()
    for matcher in _MATCHERS:
        result = matcher(norm, display)
        if result is not None:
            return result
    raise ParseError(f"Datum konnte nicht interpretiert werden: {text!r}")


def _match_exact_iso(norm, display):
    m = _RE_EXACT_ISO.match(norm)
    if not m:
        return None
    try:
        day = datetime.date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError as err:
        raise ParseError(f"Ungültiges Datum: {display!r}") from err
    return ParsedDate(earliest=day, latest=day, precision=EXACT, display=display)


def _match_exact_de(norm, display):
    m = _RE_EXACT_DE.match(norm)
    if not m:
        return None
    try:
        day = datetime.date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError as err:
        raise ParseError(f"Ungültiges Datum: {display!r}") from err
    return ParsedDate(earliest=day, latest=day, precision=EXACT, display=display)


def _match_fuzzy_year(norm, display):
    m = _RE_FUZZY.match(norm)
    if not m:
        return None
    year = _expand_year(m[1])
    return ParsedDate(
        earliest=datetime.date(year, 1, 1),
        latest=datetime.date(year, 12, 31),
        precision=YEAR,
        display=display,
    )


def _match_season(norm, display):
    m = _RE_SEASON.match(norm)
    if not m:
        return None
    start, end, spans = SEASONS[m[1]]
    year = _expand_year(m[2])
    if spans:
        earliest = datetime.date(year, start, 1)
        latest = _end_of_month(year + 1, end)
    else:
        earliest = datetime.date(year, start, 1)
        latest = _end_of_month(year, end)
    return ParsedDate(
        earliest=earliest, latest=latest, precision=SEASON, display=display
    )


def _match_decade_mod(norm, display):
    m = _RE_DECADE_MOD.match(norm)
    if not m:
        return None
    mod = _DECADE_MODS[m[1]]
    base = (_expand_year(m[2]) // 10) * 10
    return _decade_parsed(base, mod, display)


def _match_decade(norm, display):
    m = _RE_DECADE.match(norm)
    if not m:
        return None
    base = (_expand_year(m[1]) // 10) * 10
    return _decade_parsed(base, None, display)


def _decade_parsed(base, mod, display):
    if mod == "early":
        earliest = datetime.date(base, 1, 1)
        latest = datetime.date(base + 3, 12, 31)
    elif mod == "mid":
        earliest = datetime.date(base + 4, 1, 1)
        latest = datetime.date(base + 6, 12, 31)
    elif mod == "late":
        earliest = datetime.date(base + 7, 1, 1)
        latest = datetime.date(base + 9, 12, 31)
    else:
        earliest = datetime.date(base, 1, 1)
        latest = datetime.date(base + 9, 12, 31)
    return ParsedDate(
        earliest=earliest, latest=latest, precision=DECADE, display=display
    )


def _match_month_name(norm, display):
    m = _RE_MONTH_NAME.match(norm)
    if not m:
        return None
    month = MONTHS[m[1]]
    year = _expand_year(m[2])
    return _month_parsed(year, month, display)


def _match_month_iso(norm, display):
    m = _RE_MONTH_ISO.match(norm)
    if not m:
        return None
    year = int(m[1])
    month = int(m[2])
    if not 1 <= month <= 12:
        return None
    return _month_parsed(year, month, display)


def _match_month_num(norm, display):
    m = _RE_MONTH_NUM.match(norm)
    if not m:
        return None
    month = int(m[1])
    if not 1 <= month <= 12:
        raise ParseError(f"Ungültiger Monat: {display!r}")
    year = _expand_year(m[2])
    return _month_parsed(year, month, display)


def _month_parsed(year, month, display):
    return ParsedDate(
        earliest=datetime.date(year, month, 1),
        latest=_end_of_month(year, month),
        precision=MONTH,
        display=display,
    )


def _match_range(norm, display):
    m = _RE_RANGE.match(norm)
    if not m:
        return None
    start = _expand_year(m[1])
    end = _expand_year(m[2], reference=start)
    if start > end:
        raise ParseError(f"Bereich ist rückwärts: {display!r}")
    return ParsedDate(
        earliest=datetime.date(start, 1, 1),
        latest=datetime.date(end, 12, 31),
        precision=RANGE,
        display=display,
    )


def _match_year(norm, display):
    m = _RE_YEAR.match(norm)
    if not m:
        return None
    year = _expand_year(m[1])
    return ParsedDate(
        earliest=datetime.date(year, 1, 1),
        latest=datetime.date(year, 12, 31),
        precision=YEAR,
        display=display,
    )


_MATCHERS = (
    _match_exact_iso,
    _match_exact_de,
    _match_fuzzy_year,
    _match_season,
    _match_decade_mod,
    _match_decade,
    _match_month_name,
    _match_month_iso,
    _match_month_num,
    _match_range,
    _match_year,
)


def word_suggestions(prefix, limit=8):
    """Return suggestion words whose lowercased form starts with `prefix`.

    Used by the date input's inline word completion (months, seasons, fuzzy
    markers). Empty prefix returns nothing; minimum meaningful length is two
    characters to match the PLAN.md UI rule.
    """
    key = prefix.lower()
    if len(key) < 2:
        return []
    pool = MONTH_SUGGESTIONS + SEASON_SUGGESTIONS + FUZZY_SUGGESTIONS
    return [w for w in pool if w.lower().startswith(key)][:limit]
