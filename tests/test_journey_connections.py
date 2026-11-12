"""Journey hookups: phone capture, Canvas into School, calendar blocks,
the daily scan, and connecting Google from Settings."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from mindtrail.integrations import calendar_write
from mindtrail.integrations.google_api import GoogleAuthError
from mindtrail.integrations.google_connect import GoogleConnector
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize
from mindtrail.organize.journey import JourneyStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.web import journey_api, journey_daily

TODAY = date(2026, 10, 13)


@pytest.fixture
def env(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    state = AppState(path)
    journey = JourneyStore(path, state, RoadmapStore(path), RoadmapNodeStore(path))
    return journey, ProjectStore(path), state


class FakeCanvas:
    def __init__(self, events):
        self.events = events
        self.refreshed = 0

    def url(self):
        return "https://canvas.example/feed.ics"

    def refresh(self):
        self.refreshed += 1

    def upcoming(self, today, days=7):
        return self.events


def test_phone_capture_lands_in_the_chosen_journeys_suggestions(env):
    journey, projects, _ = env
    career = journey.setup(projects, 2025)["project_id"]
    health = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]

    res = journey_api.handle_capture(journey, {"text": "Apply to Stripe\nhttps://stripe.com/jobs",
                                               "project_id": career})
    again = journey_api.handle_capture(journey, {"text": "Apply to Stripe", "project_id": career})

    [s] = journey.pending(career)
    assert res == {"ok": True, "duplicate": False} and again["duplicate"] is True
    assert (s.title, s.detail, s.source) == ("Apply to Stripe", "https://stripe.com/jobs", "phone")
    assert journey.pending(health) == []
    assert "error" in journey_api.handle_capture(journey, {"text": "  ", "project_id": career})


def test_canvas_deadlines_become_school_suggestions_in_their_term(env):
    journey, projects, _ = env
    pid = journey.setup(projects, 2025)["project_id"]
    canvas = FakeCanvas([{"title": "PS 3", "due": "2027-01-20", "time": "", "uid": "a", "url": ""}])

    first = journey_api.canvas_to_school(journey, canvas, pid, TODAY)
    second = journey_api.canvas_to_school(journey, canvas, pid, TODAY)

    [s] = journey.pending(pid)
    assert (first["added"], second["added"]) == (1, 0)
    assert s.roadmap_id == journey.school_track(pid).id and s.term == "2027-winter"


def test_a_journey_without_a_school_path_takes_no_canvas_deadlines(env):
    journey, projects, _ = env
    pid = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]

    res = journey_api.canvas_to_school(journey, FakeCanvas([{"title": "x", "due": "2026-10-20"}]), pid, TODAY)

    assert res == {"added": 0}


def test_a_step_goes_on_the_calendar_at_the_local_time_picked(env):
    journey, projects, _ = env
    pid = journey.setup(projects, 2025)["project_id"]
    track = journey.school_track(pid)
    step = journey.nodes.add(track.id, "Study for midterm", "chapters 1-4")
    seen = {}

    def fake_create(title, detail, start, minutes):
        seen.update(title=title, detail=detail, start=start, minutes=minutes)
        return "https://calendar.google.com/event?eid=x"

    res = journey_api.handle_step_to_calendar(
        journey, step.id, {"date": "2026-10-14", "time": "09:30", "minutes": 90}, create=fake_create)

    assert res["link"].startswith("https://calendar.google.com")
    assert seen["title"] == "Study for midterm" and seen["minutes"] == 90
    assert seen["start"].tzinfo is not None and (seen["start"].hour, seen["start"].minute) == (9, 30)


def test_calendar_errors_and_bad_times_are_reported_not_raised(env):
    journey, projects, _ = env
    pid = journey.setup(projects, 2025)["project_id"]
    step = journey.nodes.add(journey.school_track(pid).id, "x")

    def not_connected(*args):
        raise GoogleAuthError("Google isn't connected - connect it in Settings")

    assert "Settings" in journey_api.handle_step_to_calendar(
        journey, step.id, {"date": "2026-10-14", "time": "09:00"}, create=not_connected)["error"]
    assert "error" in journey_api.handle_step_to_calendar(journey, step.id, {"date": "", "time": ""})


def test_an_event_runs_from_its_start_for_the_length_asked():
    start = datetime(2026, 10, 14, 9, 0, tzinfo=timezone(timedelta(hours=-7)))

    body = calendar_write.event_body("Study", "", start, 90)

    assert body["end"]["dateTime"] == (start + timedelta(minutes=90)).isoformat()
    with pytest.raises(ValueError):
        calendar_write.event_body("Study", "", start.replace(tzinfo=None), 60)
    with pytest.raises(ValueError):
        calendar_write.event_body("Study", "", start, 5)


def test_the_daily_scan_covers_every_journey_once_a_day(env, monkeypatch):
    journey, projects, state = env
    career = journey.setup(projects, 2025)["project_id"]
    health = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]
    scanned = []
    monkeypatch.setattr(journey_api, "handle_scan_gmail",
                        lambda *a, project_id="": scanned.append(("gmail", project_id)) or {})
    monkeypatch.setattr(journey_api, "handle_scan_calendar",
                        lambda *a, project_id="": scanned.append(("calendar", project_id)) or {})
    canvas = FakeCanvas([{"title": "PS 3", "due": "2026-10-20"}])
    deps = SimpleNamespace(state=state, journey=journey, canvas=canvas, profile=None, llm=None,
                           scanner=SimpleNamespace(_gmail=None), calendar_events=None)

    first = journey_daily.run_daily(deps, TODAY)
    second = journey_daily.run_daily(deps, TODAY)

    assert set(first) == {career, health} and second is None
    assert sorted(scanned) == sorted([("gmail", career), ("calendar", career),
                                      ("gmail", health), ("calendar", health)])
    assert canvas.refreshed == 1 and len(journey.pending(career)) == 1


def test_connecting_google_without_a_client_id_says_what_to_add(tmp_path, monkeypatch):
    monkeypatch.setattr("mindtrail.config.GOOGLE_CLIENT_ID", "")
    connector = GoogleConnector(token_path=str(tmp_path / "tok.json"))

    assert "GOOGLE_CLIENT_ID" in connector.start()["error"]
    assert connector.status()["configured"] is False and connector.status()["connected"] is False
