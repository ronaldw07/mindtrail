"""Canvas assignments from its calendar feed (Calendar -> Calendar Feed).

The feed is a private .ics link - anyone with it can read your course
calendar, no login - so it's treated like a credential: fetched through
ingest/fetch.py's SSRF-hardened path and never exported (see
life_data.PRIVATE_STATE_KEYS).

Fetched in the background at most every few hours; the Today view only
ever reads the cached copy, so a slow Canvas never slows Today down.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mindtrail.ingest.fetch import FetchError, fetch_html

URL_KEY = "canvas_ics_url"
EVENTS_KEY = "canvas_events"
DONE_KEY = "canvas_done"
REFRESH_HOURS = 6
MAX_EVENTS = 500


def _unfold(text: str) -> list[str]:
    """RFC 5545 line folding: a line starting with a space or tab
    continues the previous one."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    text = (value.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))
    return " ".join(text.split())


def _when(value: str, params: dict) -> tuple[str, str] | None:
    """(local date, local HH:MM or '') for a DTSTART value."""
    value = value.strip()
    try:
        if params.get("VALUE") == "DATE" or len(value) == 8:
            return datetime.strptime(value, "%Y%m%d").date().isoformat(), ""
        if value.endswith("Z"):
            moment = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        else:
            moment = datetime.strptime(value, "%Y%m%dT%H%M%S")
            if "TZID" in params:
                moment = moment.replace(tzinfo=ZoneInfo(params["TZID"]))
        local = moment.astimezone() if moment.tzinfo else moment
        return local.date().isoformat(), local.strftime("%H:%M")
    except (ValueError, ZoneInfoNotFoundError):
        return None


def parse_ics(text: str) -> list[dict]:
    events, current = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current and current.get("title") and current.get("due"):
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        name, _, value = line.partition(":")
        key, *raw_params = name.split(";")
        params = dict(p.split("=", 1) for p in raw_params if "=" in p)
        key = key.upper()
        if key == "SUMMARY":
            current["title"] = _unescape(value)[:200]
        elif key == "UID":
            current["uid"] = value.strip()[:200]
        elif key == "URL":
            current["url"] = value.strip() if value.strip().startswith("https://") else ""
        elif key == "DTSTART":
            when = _when(value, params)
            if when:
                current["due"], current["time"] = when
    for e in events:
        e.setdefault("uid", e["title"] + e["due"])
        e.setdefault("url", "")
    return events[:MAX_EVENTS]


def validate_feed_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("paste the https link from Canvas → Calendar → Calendar Feed")
    return url


class CanvasFeed:
    def __init__(self, state, fetch=fetch_html, clock=lambda: datetime.now(timezone.utc)):
        self._state = state
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()

    def url(self) -> str:
        return self._state.get(URL_KEY, "") or ""

    def set_url(self, url: str) -> None:
        self._state.set(URL_KEY, validate_feed_url(url) if url.strip() else "")
        self._state.set(EVENTS_KEY, {})

    def refresh(self) -> dict:
        """Fetch and cache now. Returns the cache, with "error" on failure."""
        url = self.url()
        if not url:
            return {"error": "no Canvas feed linked"}
        with self._lock:
            try:
                events = parse_ics(self._fetch(url))
            except FetchError as exc:
                cached = self._state.get(EVENTS_KEY) or {}
                return {**cached, "error": f"couldn't reach Canvas: {exc}"}
            cache = {"fetched_at": self._clock().isoformat(), "events": events}
            self._state.set(EVENTS_KEY, cache)
            return cache

    def _stale(self) -> bool:
        cache = self._state.get(EVENTS_KEY) or {}
        try:
            fetched = datetime.fromisoformat(cache["fetched_at"])
        except (KeyError, ValueError, TypeError):
            return True
        return self._clock() - fetched > timedelta(hours=REFRESH_HOURS)

    def refresh_in_background_if_stale(self) -> None:
        if self.url() and self._stale() and not self._lock.locked():
            threading.Thread(target=self.refresh, daemon=True, name="canvas-refresh").start()

    def upcoming(self, today: date, days: int = 7) -> list[dict]:
        """Not-done assignments due today through `days` ahead, soonest first."""
        done = set(self._state.get(DONE_KEY, []) or [])
        end = (today + timedelta(days=days)).isoformat()
        events = (self._state.get(EVENTS_KEY) or {}).get("events", [])
        items = [e for e in events
                 if today.isoformat() <= e["due"] <= end and e["uid"] not in done]
        return sorted(items, key=lambda e: (e["due"], e["time"] or "99:99"))

    def mark_done(self, uid: str, done: bool = True) -> None:
        current = set(self._state.get(DONE_KEY, []) or [])
        current = current | {uid} if done else current - {uid}
        self._state.set(DONE_KEY, sorted(current))
