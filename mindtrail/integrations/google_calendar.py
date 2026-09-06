"""Read-only access to the user's primary Google Calendar.

Auth (token load/refresh) lives in google_auth.py; this module makes the
one REST call the feature actually needs - GET .../calendars/primary/events -
with plain urllib rather than the full google-api-python-client, which
would be a large dependency for a single read-only endpoint (see the
comment atop ingest/fetch.py for the same reasoning applied there).

GoogleCalendarClient.snapshot() is the only thing web/api.py calls, and it
is built to never raise: a calendar outage must degrade the Today view to
"showing cached events from HH:MM" or "not connected", never a broken
dashboard. Every failure mode below is handled and turned into a plain
dict describing itself.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from mindtrail import config
from mindtrail.integrations.google_auth import default_token_path, ensure_fresh, load_credentials

CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
FETCH_WINDOW_DAYS = 7
FETCH_TIMEOUT_SECONDS = 10
MAX_EVENTS = 50

# 15 minutes: long enough that the dashboard's every-visit reload never
# waits on Google, short enough that a newly-added meeting shows up
# within one working session rather than needing a manual refresh.
CACHE_TTL_SECONDS = 15 * 60


class CalendarAuthError(RuntimeError):
    """The refresh token no longer works (expired or revoked in the
    Google Account's connected-apps settings). Surfaced as "reconnect
    Google Calendar", never a crash or a silent retry loop."""


class CalendarFetchError(RuntimeError):
    """Network failure, timeout, or a non-auth API error. The caller
    falls back to a cached snapshot rather than propagating this."""


def default_cache_path() -> str:
    return str(Path(config.CHROMA_DIR).parent / "google_calendar_cache.json")


def _event_to_dict(item: dict) -> dict:
    """Google represents an all-day event as {"date": "YYYY-MM-DD"} and a
    timed one as {"dateTime": "...", "timeZone": "..."} - two different
    shapes callers have to branch on, not a formatting detail. `date` is
    always the event's local calendar day (used to filter "today");
    `start` is what a human reads: the date again for an all-day event,
    or an HH:MM for a timed one, converted to local time so a meeting
    invited across timezones still shows the time the user will actually
    see on their clock.
    """
    start = item.get("start", {})
    title = item.get("summary") or "(no title)"
    if "date" in start:
        return {"title": title, "all_day": True, "date": start["date"], "start": start["date"]}

    raw = start.get("dateTime", "")
    try:
        local = datetime.fromisoformat(raw).astimezone()
    except ValueError:
        return {"title": title, "all_day": False, "date": "", "start": ""}
    return {
        "title": title, "all_day": False,
        "date": local.date().isoformat(), "start": local.strftime("%H:%M"),
    }


def fetch_week_events(creds: Credentials, token_path: str) -> list[dict]:
    """Today through the next FETCH_WINDOW_DAYS days, in local time, from
    the primary calendar only (see the module docstring for why this is
    a plain urllib call rather than a client library call).

    Raises CalendarAuthError if the refresh token no longer works,
    CalendarFetchError for anything else - GoogleCalendarClient decides
    what to show the user for each.
    """
    try:
        creds = ensure_fresh(creds, token_path)
    except RefreshError as exc:
        raise CalendarAuthError(f"Google Calendar authorization expired: {exc}") from exc

    # Local midnight, not UTC midnight - see api.py's _agenda_bucket
    # comment for why "today" is always computed in local time here.
    local_midnight = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    params = {
        "timeMin": local_midnight.isoformat(),
        "timeMax": (local_midnight + timedelta(days=FETCH_WINDOW_DAYS)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(MAX_EVENTS),
    }
    url = f"{CALENDAR_EVENTS_URL}?{urlencode(params)}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {creds.token}"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise CalendarAuthError(f"Google Calendar denied the request: {exc}") from exc
        raise CalendarFetchError(f"Google Calendar request failed: {exc}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise CalendarFetchError(f"could not reach Google Calendar: {exc}") from exc

    return [_event_to_dict(item) for item in payload.get("items", [])]


def _read_cache(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _write_cache(path: str, events: list[dict], fetched_at: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"fetched_at": fetched_at, "events": events}, f)


def _cache_is_fresh(cache: dict, now: datetime) -> bool:
    try:
        fetched_at = datetime.fromisoformat(cache["fetched_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return (now - fetched_at).total_seconds() < CACHE_TTL_SECONDS


def _todays_events(events: list[dict], today_iso: str) -> list[dict]:
    """Only today's occurrences, all-day events first, then timed events
    in start-time order - the fetch covers a week so the cache stays
    useful across the TTL, but the daily summary's job is answering
    "what's on today", not the whole week."""
    todays = [e for e in events if e.get("date") == today_iso]
    return sorted(todays, key=lambda e: (0 if e["all_day"] else 1, e["start"]))


class GoogleCalendarClient:
    """The single entry point web/api.py uses: `.snapshot()` returns a
    plain, JSON-ready dict and never raises.

    `fetch` and `clock` are injectable so tests can exercise the cache-hit
    / cache-stale-fetch-fails / token-expired paths without any real
    network call or real wall-clock timing.
    """

    def __init__(
        self,
        token_path: str | None = None,
        cache_path: str | None = None,
        fetch=fetch_week_events,
        clock=lambda: datetime.now().astimezone(),
    ):
        self._token_path = token_path or default_token_path()
        self._cache_path = cache_path or default_cache_path()
        self._fetch = fetch
        self._clock = clock

    def snapshot(self) -> dict:
        creds = load_credentials(self._token_path)
        if creds is None:
            return {"connected": False}

        now = self._clock()
        today_iso = now.date().isoformat()
        cache = _read_cache(self._cache_path)
        if cache is not None and _cache_is_fresh(cache, now):
            return self._snapshot_from_cache(cache, today_iso, stale=False)

        try:
            events = self._fetch(creds, self._token_path)
        except CalendarAuthError:
            if cache is not None:
                snap = self._snapshot_from_cache(cache, today_iso, stale=True)
                snap["needs_reconnect"] = True
                return snap
            return {"connected": False, "needs_reconnect": True}
        except CalendarFetchError as exc:
            if cache is not None:
                snap = self._snapshot_from_cache(cache, today_iso, stale=True)
                snap["error"] = str(exc)
                return snap
            return {"connected": True, "events": [], "as_of": "", "stale": False, "error": str(exc)}

        fetched_at = now.isoformat()
        _write_cache(self._cache_path, events, fetched_at)
        return {
            "connected": True,
            "events": _todays_events(events, today_iso),
            "as_of": now.strftime("%H:%M"),
            "stale": False,
        }

    def _snapshot_from_cache(self, cache: dict, today_iso: str, stale: bool) -> dict:
        fetched_at = datetime.fromisoformat(cache["fetched_at"])
        return {
            "connected": True,
            "events": _todays_events(cache.get("events", []), today_iso),
            "as_of": fetched_at.strftime("%H:%M"),
            "stale": stale,
        }
