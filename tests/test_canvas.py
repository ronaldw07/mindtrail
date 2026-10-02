"""Canvas calendar feed: parsing, caching, privacy, and Today's use of it."""

from datetime import date, datetime, timedelta, timezone

import pytest

from mindtrail.ingest.fetch import FetchError
from mindtrail.integrations.canvas import CanvasFeed, parse_ics, validate_feed_url
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize
from mindtrail.organize.life_data import dump_tables
from mindtrail.web import admin_api
from mindtrail.web.today import pick_top_priority

ICS = (
    "BEGIN:VCALENDAR\r\n"
    "BEGIN:VEVENT\r\nUID:a1\r\nSUMMARY:Homework 3 [CS 161]\r\n"
    "DTSTART;VALUE=DATE:20261003\r\nURL:https://canvas.example.edu/a/1\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:a2\r\nSUMMARY:Quiz\\, part 2 \r\n  (online)\r\n"
    "DTSTART:20261005T065900Z\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:a3\r\nSUMMARY:Lab\r\n"
    "DTSTART;TZID=America/New_York:20261004T235900\r\nURL:javascript:alert(1)\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nSUMMARY:No date\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)
THU = date(2026, 10, 1)


@pytest.fixture
def state(tmp_path):
    db = str(tmp_path / "t.db")
    initialize(db)
    return AppState(db)


def test_parse_dates_folding_escapes_and_unsafe_urls():
    events = {e["uid"]: e for e in parse_ics(ICS)}
    assert set(events) == {"a1", "a2", "a3"}
    assert (events["a1"]["due"], events["a1"]["time"]) == ("2026-10-03", "")
    assert events["a1"]["url"] == "https://canvas.example.edu/a/1"
    assert events["a2"]["title"] == "Quiz, part 2 (online)"
    utc = datetime(2026, 10, 5, 6, 59, tzinfo=timezone.utc).astimezone()
    assert (events["a2"]["due"], events["a2"]["time"]) == (utc.date().isoformat(), utc.strftime("%H:%M"))
    assert events["a3"]["url"] == ""


def test_feed_url_must_be_https():
    with pytest.raises(ValueError):
        validate_feed_url("http://canvas.example.edu/feed.ics")
    with pytest.raises(ValueError):
        validate_feed_url("file:///etc/passwd")


def test_refresh_caches_and_upcoming_hides_done(state):
    feed = CanvasFeed(state, fetch=lambda url: ICS)
    feed.set_url("https://canvas.example.edu/feeds/calendars/user_x.ics")
    feed.refresh()
    assert [e["uid"] for e in feed.upcoming(THU)][:1] == ["a1"]
    feed.mark_done("a1")
    assert "a1" not in [e["uid"] for e in feed.upcoming(THU)]
    assert feed.upcoming(THU + timedelta(days=30)) == []


def test_fetch_failure_keeps_the_last_good_copy(state):
    feed = CanvasFeed(state, fetch=lambda url: ICS)
    feed.set_url("https://canvas.example.edu/x.ics")
    feed.refresh()

    def down(url):
        raise FetchError("timeout")
    failed = CanvasFeed(state, fetch=down).refresh()
    assert "error" in failed and len(failed["events"]) == 3


def test_the_feed_link_never_leaves_in_status_or_backup(state, tmp_path):
    feed = CanvasFeed(state, fetch=lambda url: ICS)
    secret = "https://canvas.example.edu/feeds/calendars/user_SECRET.ics"
    status = admin_api.handle_set_canvas(feed, state, {"url": secret})
    assert status["linked"] and status["count"] == 3 and "SECRET" not in str(status)
    assert "SECRET" not in str(dump_tables(state._path))


def test_assignment_due_today_can_lead_the_day():
    top = pick_top_priority({"assignments": [{"title": "HW", "due": THU.isoformat(),
                                              "uid": "a", "time": ""}],
                             "unblocked": [{"title": "step", "due_date": ""}]}, THU)
    assert top["kind"] == "assignment" and top["title"] == "HW"
