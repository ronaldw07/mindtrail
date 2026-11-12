"""School terms: quarters plus summer, named like "2026-fall".

The year in a term is the calendar year it happens in, so an academic
year starting in 2025 is 2025-fall, 2026-winter, 2026-spring, 2026-summer.
Boundaries follow UCI's quarter calendar closely enough for a "Now" line:
winter is January to March, spring April to mid June, summer mid June to
late September, fall the rest.
"""

from __future__ import annotations

import re
from datetime import date

SEASONS = ("fall", "winter", "spring", "summer")
"""In the order they come within one academic year."""

_TERM = re.compile(r"^(\d{4})-(fall|winter|spring|summer)$")
# Chronological rank within one calendar year.
_CALENDAR_RANK = {"winter": 0, "spring": 1, "summer": 2, "fall": 3}
SUMMER_STARTS = (6, 15)
FALL_STARTS = (9, 22)


def is_term(value: str) -> bool:
    return bool(_TERM.match(value or ""))


def clean_term(value) -> str:
    """'' or a valid term, else ValueError."""
    term = str(value or "").strip().lower()
    if term and not is_term(term):
        raise ValueError(f"not a term (like 2026-fall): {value}")
    return term


def _split(term: str) -> tuple[int, str]:
    match = _TERM.match(term)
    if not match:
        raise ValueError(f"not a term: {term}")
    return int(match.group(1)), match.group(2)


def term_of(day: date) -> str:
    md = (day.month, day.day)
    if day.month <= 3:
        season = "winter"
    elif md < SUMMER_STARTS:
        season = "spring"
    elif md < FALL_STARTS:
        season = "summer"
    else:
        season = "fall"
    return f"{day.year}-{season}"


def term_rank(term: str) -> int:
    """Sortable: a later term always ranks higher."""
    year, season = _split(term)
    return year * 4 + _CALENDAR_RANK[season]


def next_term(term: str) -> str:
    year, season = _split(term)
    if season == "fall":
        return f"{year + 1}-winter"
    order = ("winter", "spring", "summer", "fall")
    return f"{year}-{order[order.index(season) + 1]}"


def year_terms(start_year: int, year_number: int) -> list[str]:
    """The four terms of academic year `year_number` (1-based)."""
    fall = start_year + year_number - 1
    return [f"{fall}-fall", f"{fall + 1}-winter", f"{fall + 1}-spring", f"{fall + 1}-summer"]


def year_of(term: str, start_year: int) -> int:
    """1-based academic year a term falls in (can be <1 or >4)."""
    year, season = _split(term)
    return year - start_year + (1 if season == "fall" else 0)


def term_label(term: str) -> str:
    year, season = _split(term)
    return f"{season.title()} {year}"
