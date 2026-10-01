"""Natural due dates at the end of a to-do: "Email Carla back fri".

Only a date phrase at the very end counts, so a title that merely
mentions a day ("Plan Friday's party") keeps its words. Parsed in code -
quick-add must be instant and free.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

WEEKDAYS = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4,
    "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8,
    "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
RELATIVE = {"today": 0, "tonight": 0, "tomorrow": 1, "tmrw": 1, "tmr": 1}

_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_MO = "|".join(sorted(MONTHS, key=len, reverse=True))
_REL = "|".join(RELATIVE)
_CONNECTOR = r"(?:\s+(?:by|on|due|before))?"
_PATTERNS = (
    ("relative", rf"({_REL})"),
    ("next_week", r"next\s+week"),
    ("next_weekday", rf"next\s+({_WD})"),
    ("weekday", rf"(?:this\s+)?({_WD})"),
    ("in", r"in\s+(\d{1,3})\s+(day|days|week|weeks)"),
    ("month_day", rf"({_MO})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?"),
    ("day_month", rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MO})"),
    ("numeric", r"(\d{1,2})/(\d{1,2})"),
)


def _upcoming(month: int, day: int, today: date) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate >= today:
            return candidate
    return None


def _resolve(kind: str, groups: tuple, today: date) -> date | None:
    if kind == "relative":
        return today + timedelta(days=RELATIVE[groups[0]])
    if kind == "next_week":
        return today + timedelta(days=7 - today.weekday())
    if kind == "weekday":
        return today + timedelta(days=(WEEKDAYS[groups[0]] - today.weekday()) % 7)
    if kind == "next_weekday":
        days = (WEEKDAYS[groups[0]] - today.weekday()) % 7
        return today + timedelta(days=days + 7 if days else 7)
    if kind == "in":
        n = int(groups[0])
        return today + timedelta(days=n * 7 if groups[1].startswith("week") else n)
    if kind == "month_day":
        return _upcoming(MONTHS[groups[0]], int(groups[1]), today)
    if kind == "day_month":
        return _upcoming(MONTHS[groups[1]], int(groups[0]), today)
    if kind == "numeric":
        return _upcoming(int(groups[0]), int(groups[1]), today)
    return None


def parse_task_input(text: str, today: date) -> tuple[str, str]:
    """(title, YYYY-MM-DD or '') from free text like "Call mom tmrw"."""
    text = " ".join(text.split())
    for kind, pattern in _PATTERNS:
        match = re.search(rf"{_CONNECTOR}\s+{pattern}$", " " + text, re.IGNORECASE)
        if not match:
            continue
        title = (" " + text)[: match.start()].strip(" ,-")
        due = _resolve(kind, tuple(g.lower() for g in match.groups()), today)
        if title and due is not None:
            return title, due.isoformat()
    return text, ""
