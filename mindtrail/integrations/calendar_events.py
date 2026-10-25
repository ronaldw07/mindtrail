"""Google Calendar events over a window, for the journey's suggestions.

The Today view reads a week at a time through google_calendar.py. The
journey needs to see further ahead (exams, deadlines, interviews a few
weeks out), so this is a separate small read: titles and dates only -
no attendees, descriptions or locations leave this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from mindtrail.integrations.google_api import credentials_for, get_json
from mindtrail.integrations.google_auth import CALENDAR_SCOPE

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
PAGE_SIZE = 100


@dataclass(frozen=True)
class CalendarEvent:
    date: str  # local YYYY-MM-DD
    title: str
    all_day: bool


def parse_event(item: dict) -> CalendarEvent | None:
    """None for a cancelled event or one with no usable title or date."""
    if item.get("status") == "cancelled":
        return None
    title = " ".join(str(item.get("summary", "")).split())[:120]
    start = item.get("start", {})
    if not title:
        return None
    if "date" in start:
        return CalendarEvent(start["date"], title, True)
    try:
        local = datetime.fromisoformat(start.get("dateTime", "")).astimezone()
    except ValueError:
        return None
    return CalendarEvent(local.date().isoformat(), title, False)


class CalendarEvents:
    """`get` is injectable so tests never touch the network."""

    def __init__(self, token_path: str | None = None, get=get_json):
        self._token_path = token_path
        self._get = get

    def between(self, start: date, end: date, limit: int = PAGE_SIZE) -> list[CalendarEvent]:
        """Events from `start` up to (not including) `end`, soonest first."""
        creds, path = credentials_for(CALENDAR_SCOPE, "Calendar", self._token_path)
        params = {
            "timeMin": datetime.combine(start, time.min).astimezone().isoformat(),
            "timeMax": datetime.combine(end, time.min).astimezone().isoformat(),
            "singleEvents": "true", "orderBy": "startTime", "maxResults": min(limit, 250),
        }
        data = self._get(creds, path, EVENTS_URL, params)
        events = [e for e in map(parse_event, data.get("items", [])) if e]
        return events[:limit]
