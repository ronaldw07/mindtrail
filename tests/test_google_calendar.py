"""GoogleCalendarClient.snapshot() - the cache, staleness, and error-
handling logic. No real Google credentials or network calls: `fetch` and
`clock` are injected stubs, per the client's own design for exactly this.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta

import pytest

from mindtrail.integrations.google_calendar import (
    CalendarAuthError,
    CalendarFetchError,
    GoogleCalendarClient,
)


class StubCredentials:
    token = "access-token"


def _fetch_returning(events, calls_log=None):
    def fetch(creds, token_path):
        if calls_log is not None:
            calls_log.append(1)
        return events

    return fetch


def _fetch_raising(exc):
    def fetch(creds, token_path):
        raise exc

    return fetch


def _client(tmp_path, fetch, now, connected=True):
    token_path = str(tmp_path / "google_token.json")
    if connected:
        with open(token_path, "w") as f:
            json.dump(
                {
                    "token": "t", "refresh_token": "r",
                    "client_id": "c", "client_secret": "s",
                },
                f,
            )
    return GoogleCalendarClient(
        token_path=token_path,
        cache_path=str(tmp_path / "google_calendar_cache.json"),
        fetch=fetch,
        clock=lambda: now,
    )


def an_event(title="Standup", start="09:00", all_day=False, date=None):
    return {
        "title": title, "start": start, "all_day": all_day,
        "date": date or datetime.now().astimezone().date().isoformat(),
    }


# --- never connected ----------------------------------------------------


def test_never_connected_reports_not_connected_without_fetching(tmp_path):
    calls = []
    client = _client(tmp_path, _fetch_returning([], calls), now=datetime.now(), connected=False)

    snapshot = client.snapshot()

    assert snapshot == {"connected": False}
    assert calls == []


# --- connected, live fetch ------------------------------------------------


def test_connected_with_events_returns_todays_events(tmp_path):
    now = datetime.now().astimezone()
    today = now.date().isoformat()
    events = [an_event("Standup", "09:00", date=today), an_event("Gym", "18:00", date=today)]
    client = _client(tmp_path, _fetch_returning(events), now=now)

    snapshot = client.snapshot()

    assert snapshot["connected"] is True
    assert [e["title"] for e in snapshot["events"]] == ["Standup", "Gym"]
    assert snapshot["stale"] is False


def test_connected_with_no_events_today_returns_an_empty_list(tmp_path):
    now = datetime.now().astimezone()
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    client = _client(tmp_path, _fetch_returning([an_event(date=tomorrow)]), now=now)

    snapshot = client.snapshot()

    assert snapshot["connected"] is True
    assert snapshot["events"] == []


def test_all_day_events_sort_before_timed_events(tmp_path):
    now = datetime.now().astimezone()
    today = now.date().isoformat()
    events = [
        an_event("Standup", "09:00", date=today),
        an_event("Conference", all_day=True, start=today, date=today),
    ]
    client = _client(tmp_path, _fetch_returning(events), now=now)

    snapshot = client.snapshot()

    assert [e["title"] for e in snapshot["events"]] == ["Conference", "Standup"]


# --- cache ----------------------------------------------------------------


def test_a_fresh_cache_hit_never_calls_fetch(tmp_path):
    now = datetime.now().astimezone()
    today = now.date().isoformat()
    calls = []
    client = _client(tmp_path, _fetch_returning([an_event(date=today)], calls), now=now)
    client.snapshot()  # populates the cache
    assert len(calls) == 1

    second = client.snapshot()

    assert len(calls) == 1  # still one - served from cache
    assert second["stale"] is False


def test_a_stale_cache_that_fails_to_refetch_serves_the_cached_events(tmp_path):
    now = datetime.now().astimezone()
    today = now.date().isoformat()
    client = _client(tmp_path, _fetch_returning([an_event("Standup", date=today)]), now=now)
    client.snapshot()  # populates the cache

    later = now + timedelta(minutes=20)  # past the 15-minute TTL
    failing_client = GoogleCalendarClient(
        token_path=client._token_path, cache_path=client._cache_path,
        fetch=_fetch_raising(CalendarFetchError("network down")), clock=lambda: later,
    )

    snapshot = failing_client.snapshot()

    assert snapshot["connected"] is True
    assert snapshot["stale"] is True
    assert snapshot["events"][0]["title"] == "Standup"
    assert "network down" in snapshot["error"]


def test_fetch_failure_with_no_cache_at_all_still_reports_connected(tmp_path):
    now = datetime.now().astimezone()
    client = _client(tmp_path, _fetch_raising(CalendarFetchError("timed out")), now=now)

    snapshot = client.snapshot()

    assert snapshot["connected"] is True
    assert snapshot["events"] == []
    assert "timed out" in snapshot["error"]


# --- token expiry / revocation --------------------------------------------


def test_expired_token_with_no_cache_reports_needing_reconnect(tmp_path):
    now = datetime.now().astimezone()
    client = _client(tmp_path, _fetch_raising(CalendarAuthError("revoked")), now=now)

    snapshot = client.snapshot()

    assert snapshot["connected"] is False
    assert snapshot["needs_reconnect"] is True


def test_expired_token_with_a_cache_serves_cached_events_and_flags_reconnect(tmp_path):
    now = datetime.now().astimezone()
    today = now.date().isoformat()
    client = _client(tmp_path, _fetch_returning([an_event("Standup", date=today)]), now=now)
    client.snapshot()  # populates the cache

    later = now + timedelta(minutes=20)
    revoked_client = GoogleCalendarClient(
        token_path=client._token_path, cache_path=client._cache_path,
        fetch=_fetch_raising(CalendarAuthError("revoked")), clock=lambda: later,
    )

    snapshot = revoked_client.snapshot()

    assert snapshot["connected"] is True
    assert snapshot["needs_reconnect"] is True
    assert snapshot["stale"] is True
    assert snapshot["events"][0]["title"] == "Standup"


# --- cache file permissions ------------------------------------------------


def test_cache_file_is_written_privately(tmp_path):
    now = datetime.now().astimezone()
    today = now.date().isoformat()
    client = _client(tmp_path, _fetch_returning([an_event(date=today)]), now=now)

    client.snapshot()

    mode = stat.S_IMODE(os.stat(client._cache_path).st_mode)
    assert mode == 0o600
