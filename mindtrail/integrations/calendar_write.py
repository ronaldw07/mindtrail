"""Putting a journey step on Google Calendar as a time block.

The only write Mind Trail makes to Google, and only when you click it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mindtrail.integrations.google_api import credentials_for, post_json
from mindtrail.integrations.google_auth import CALENDAR_EVENTS_SCOPE

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
MIN_MINUTES, MAX_MINUTES = 15, 8 * 60


def event_body(title: str, detail: str, start: datetime, minutes: int) -> dict:
    """Raises ValueError for a missing title, a naive start, or a silly length."""
    if not title.strip():
        raise ValueError("the block needs a title")
    if start.tzinfo is None:
        raise ValueError("start time needs a timezone")
    if not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise ValueError(f"length must be {MIN_MINUTES}-{MAX_MINUTES} minutes")
    end = start + timedelta(minutes=minutes)
    return {
        "summary": title.strip(),
        "description": detail.strip(),
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }


def create_event(title: str, detail: str, start: datetime, minutes: int,
                 token_path: str | None = None, post=post_json) -> str:
    """Create the event and return its link in Google Calendar."""
    body = event_body(title, detail, start, minutes)
    creds, path = credentials_for(CALENDAR_EVENTS_SCOPE, "adding to your calendar", token_path)
    return str(post(creds, path, EVENTS_URL, body).get("htmlLink", ""))
