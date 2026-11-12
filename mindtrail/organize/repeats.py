"""Repeating to-dos: "Water plants every mon", "Pay rent 1st of every month".

A rule is a short string:
  day:N            every N days
  week:N           every N weeks, same weekday as the last due date
  week:N:D         every N weeks on weekday D (0 = Monday)
  month:N          every N months, same day of the month
  month:N:D        every N months on day D (clamped to the month's length)

Parsed in code, like the due dates in task_dates.py, so quick-add stays
instant and free. Only a phrase at the end of the title counts.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from mindtrail.organize.task_dates import WEEKDAYS, parse_task_input

_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_ORD = r"(\d{1,2})(?:st|nd|rd|th)"
_PATTERNS = (
    (rf"every\s+other\s+({_WD})s?", lambda m: f"week:2:{WEEKDAYS[m.group(1).lower()]}"),
    (rf"every\s+({_WD})s?", lambda m: f"week:1:{WEEKDAYS[m.group(1).lower()]}"),
    (r"every\s+(\d{1,2})\s+(day|week|month)s?", lambda m: f"{m.group(2).lower()}:{int(m.group(1))}"),
    (rf"(?:on\s+)?(?:the\s+)?{_ORD}\s+of\s+(?:every|each)\s+month", lambda m: f"month:1:{int(m.group(1))}"),
    (rf"(?:on\s+)?(?:the\s+)?{_ORD}\s+of\s+(?:the\s+)?month", lambda m: f"month:1:{int(m.group(1))}"),
    (rf"every\s+{_ORD}", lambda m: f"month:1:{int(m.group(1))}"),
    (r"(?:every|each)\s+day|daily", lambda m: "day:1"),
    (r"(?:every|each)\s+week|weekly", lambda m: "week:1"),
    (r"(?:every|each)\s+month|monthly", lambda m: "month:1"),
)
_COMPILED = [(re.compile(rf"(?:^|\s)(?:{p})$", re.IGNORECASE), build) for p, build in _PATTERNS]
_RULE = re.compile(r"^(day|week|month):(\d{1,2})(?::(\d{1,2}))?$")


def parse_repeat(text: str) -> tuple[str, str]:
    """(title without the phrase, rule) - or (text, "") if it doesn't repeat."""
    text = " ".join(text.split())
    for pattern, build in _COMPILED:
        match = pattern.search(text)
        if not match:
            continue
        title = text[: match.start()].strip(" ,-")
        if title:
            return title, build(match)
    return text, ""


def _parse_rule(rule: str):
    m = _RULE.match(rule)
    if not m:
        raise ValueError(f"bad repeat rule: {rule!r}")
    return m.group(1), int(m.group(2)), (int(m.group(3)) if m.group(3) is not None else None)


def _month_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _add_months(base: date, n: int, day: int | None = None) -> date:
    index = base.year * 12 + (base.month - 1) + n
    return _month_day(index // 12, index % 12 + 1, day if day is not None else base.day)


def next_due(rule: str, last_due: str, today: date) -> str:
    """The first occurrence after both the last due date and today - so a
    task finished late skips the occurrences that were missed."""
    unit, n, anchor = _parse_rule(rule)
    base = date.fromisoformat(last_due) if last_due else today
    floor = max(base, today)

    def after(step) -> date:
        candidate, k = step(1), 1
        while candidate <= floor:
            k += 1
            candidate = step(k)
        return candidate

    if unit == "day":
        return after(lambda k: base + timedelta(days=n * k)).isoformat()
    if unit == "week":
        if anchor is None:
            return after(lambda k: base + timedelta(weeks=n * k)).isoformat()
        delta = (anchor - base.weekday()) % 7
        first = base + timedelta(days=delta if delta else 7 * n)
        return after(lambda k: first + timedelta(weeks=n * (k - 1))).isoformat()
    # month: anchored day, or the base date's own day
    anchor_day = anchor if anchor is not None else base.day
    return after(lambda k: _add_months(base.replace(day=1), n * k, anchor_day)).isoformat()


def first_due(rule: str, today: date) -> str:
    """When a brand-new repeating task is first due."""
    unit, n, anchor = _parse_rule(rule)
    if unit == "week" and anchor is not None:
        return (today + timedelta(days=(anchor - today.weekday()) % 7)).isoformat()
    if unit == "month" and anchor is not None:
        this_month = _month_day(today.year, today.month, anchor)
        return (this_month if this_month >= today else _add_months(today.replace(day=1), 1, anchor)).isoformat()
    return today.isoformat()


def parse_task_with_repeat(text: str, today: date) -> tuple[str, str, str]:
    """(title, due date or "", rule or "") from quick-add text. An explicit
    date phrase at the end wins over the rule's first date."""
    # The repeat phrase may be last ("... every mon") or sit before a date
    # ("... every mon oct 20"). Try it last-first, or "mon" would be read as
    # a due date and strand the word "every" in the title.
    title, rule = parse_repeat(text)
    if rule:
        title, due = parse_task_input(title, today)
        return title, due or first_due(rule, today), rule
    title, due = parse_task_input(text, today)
    title, rule = parse_repeat(title)
    if not rule:
        return title, due, ""
    return title, due or first_due(rule, today), rule


_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def describe(rule: str) -> str:
    if not rule:
        return ""
    unit, n, anchor = _parse_rule(rule)
    if unit == "day":
        return "Every day" if n == 1 else f"Every {n} days"
    if unit == "week":
        if anchor is not None:
            return f"Every {_DAY_NAMES[anchor]}" if n == 1 else (
                f"Every other {_DAY_NAMES[anchor]}" if n == 2 else f"Every {n} weeks on {_DAY_NAMES[anchor]}")
        return "Every week" if n == 1 else f"Every {n} weeks"
    base = "Every month" if n == 1 else f"Every {n} months"
    return f"{base} on the {_ordinal(anchor)}" if anchor is not None else base
