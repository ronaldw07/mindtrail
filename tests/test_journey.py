"""The journey: setup, tracks, reflections, suggestions, and the API on top."""

from datetime import date

import pytest

from mindtrail.advice import journey_ai
from mindtrail.integrations.gemini_takeout import parse_takeout
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize
from mindtrail.organize.journey import JourneyStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore, duplicate_roadmap
from mindtrail.web import journey_api

TODAY = date(2026, 10, 13)  # 2026-fall, Year 2


@pytest.fixture
def env(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    roadmaps, nodes = RoadmapStore(path), RoadmapNodeStore(path)
    projects = ProjectStore(path)
    journey = JourneyStore(path, AppState(path), roadmaps, nodes)
    return journey, projects, roadmaps, nodes


def test_duplicate_copies_steps_and_links_without_touching_the_source(env):
    journey, projects, roadmaps, nodes = env
    p = projects.create("career")
    src = roadmaps.create("PM internships", p.id)
    a = nodes.add(src.id, "Resume", status="done", term="2026-fall")
    b = nodes.add(src.id, "Apply", depends_on=[a.id])

    copy = duplicate_roadmap(roadmaps, nodes, src.id, "PM copy")

    steps = nodes.for_roadmap(copy.id)
    assert {s.title for s in steps} == {"Resume", "Apply"}
    assert not {s.id for s in steps} & {a.id, b.id}
    apply_copy = next(s for s in steps if s.title == "Apply")
    resume_copy = next(s for s in steps if s.title == "Resume")
    assert apply_copy.depends_on == (resume_copy.id,)
    assert resume_copy.status == "done" and resume_copy.term == "2026-fall"
    assert [n.id for n in nodes.for_roadmap(src.id)] == [a.id, b.id]


def test_setup_builds_tracks_and_copies_the_career_roadmap_once(env):
    journey, projects, roadmaps, nodes = env
    career = projects.create("career")
    src = roadmaps.create("PM", career.id)
    nodes.add(src.id, "Step one")

    saved = journey.setup(projects, 2025, [src.id])

    shared, others = journey.tracks(saved["project_id"])
    assert shared is not None and shared.kind == "shared"
    assert [r.name for r in others] == ["AI/ML", "SWE", "Product Eng", "From career"]
    assert len(roadmaps.list_for_project(career.id)) == 1  # original untouched
    assert [n.title for n in nodes.for_roadmap(src.id)] == ["Step one"]
    with pytest.raises(ValueError):
        journey.setup(projects, 2025)


def test_dismissed_suggestions_do_not_come_back_and_accept_applies(env):
    journey, projects, roadmaps, nodes = env
    pid = journey.setup(projects, 2025)["project_id"]
    shared, _ = journey.tracks(pid)

    s = journey.add_suggestion(pid, "gmail", "add_done", "Joined ACM", term="2025-fall",
                               roadmap_id=shared.id)
    assert journey.add_suggestion(pid, "gemini", "add_done", "joined  acm") is None
    node_id = journey.accept_suggestion(s.id)
    assert nodes.get(node_id).status == "done" and nodes.get(node_id).term == "2025-fall"
    with pytest.raises(ValueError):
        journey.accept_suggestion(s.id)

    t = journey.add_suggestion(pid, "gmail", "add_step", "Do a thing")
    journey.dismiss_suggestion(t.id)
    assert journey.add_suggestion(pid, "gmail", "add_step", "Do a thing") is None


def test_reflections_upsert(env):
    journey, projects, *_ = env
    pid = journey.setup(projects, 2025)["project_id"]
    journey.set_reflection(pid, "2025-fall", "took CS 31")
    journey.set_reflection(pid, "2025-fall", "took CS 31 and 32")
    assert journey.reflections(pid) == {"2025-fall": "took CS 31 and 32"}
    with pytest.raises(ValueError):
        journey.set_reflection(pid, "fall", "x")


def test_get_before_and_after_setup_and_next_up(env):
    journey, projects, roadmaps, nodes = env
    before = journey_api.handle_get(journey, projects, TODAY)
    assert before["setup"] is False and before["start_year"] == 2026

    pid = journey.setup(projects, 2025)["project_id"]
    _, others = journey.tracks(pid)
    nodes.add(others[0].id, "Old thing", status="accepted", term="2026-spring")
    nodes.add(others[0].id, "Now thing", status="accepted", term="2026-fall")
    nodes.add(others[0].id, "Far thing", status="accepted", term="2028-fall")
    nodes.add(others[0].id, "Finished", status="done", term="2026-fall")
    data = journey_api.handle_get(journey, projects, TODAY)

    assert data["current_term"] == "2026-fall" and data["current_year"] == 2
    assert [y["number"] for y in data["years"]] == [1, 2, 3, 4]
    cur = [t for y in data["years"] for t in y["terms"] if t["current"]]
    assert len(cur) == 1 and cur[0]["term"] == "2026-fall"
    assert [s["title"] for s in data["next_up"]] == [
        "Old thing", "Now thing", "Apply for summer internships"]
    today = journey_api.handle_today(journey, projects, TODAY)
    assert today["total"] == 4 and today["done"] == 1


def test_move_step_changes_term_and_track_and_rejects_foreign_steps(env):
    journey, projects, roadmaps, nodes = env
    pid = journey.setup(projects, 2025)["project_id"]
    _, (a, b, *_) = journey.tracks(pid)
    n = nodes.add(a.id, "Leetcode", term="2026-fall")

    assert journey_api.handle_move_step(journey, n.id, {"term": "2027-winter", "track_id": b.id}) == {"ok": True}
    moved = nodes.get(n.id)
    assert moved.term == "2027-winter" and moved.roadmap_id == b.id
    assert "error" in journey_api.handle_move_step(journey, n.id, {"term": "winter"})

    other = projects.create("elsewhere")
    foreign = nodes.add(roadmaps.create("x", other.id).id, "nope")
    assert "error" in journey_api.handle_move_step(journey, foreign.id, {"term": "2027-winter"})


class FakeLLM:
    def __init__(self, text):
        self.text = text

    def complete(self, system, user, max_tokens=900):
        class C:
            pass
        c = C()
        c.text = self.text
        self.last_user = user
        return c


def _ctx(env):
    journey, projects, roadmaps, nodes = env
    pid = journey.setup(projects, 2025)["project_id"]
    shared, others = journey.tracks(pid)
    n = nodes.add(others[0].id, "LeetCode prep", term="2026-fall")
    steps = {r.id: nodes.for_roadmap(r.id) for r in [shared] + others}
    return journey_ai.build_context(2025, "2026-fall", shared, others, steps), others[0], n, shared


def test_chat_drops_actions_with_unknown_ids_or_bad_terms(env):
    ctx, track, node, shared = _ctx(env)
    text = ('{"reply": "Proposed.", "actions": ['
            f'{{"type": "move_term", "node_id": "{node.id}", "term": "2027-spring"}},'
            '{"type": "move_term", "node_id": "made-up", "term": "2027-spring"},'
            f'{{"type": "move_term", "node_id": "{node.id}", "term": "spring"}},'
            f'{{"type": "add_step", "track_id": "{track.id}", "title": "Research", "term": "2027-fall"}},'
            '{"type": "add_step", "track_id": "nope", "title": "X"},'
            '{"type": "create_track", "name": "Research"}]}')
    reply, actions = journey_ai.parse_chat(text, ctx)
    assert reply == "Proposed."
    assert [a.type for a in actions] == ["move_term", "add_step", "create_track"]
    assert "Spring 2027" in actions[0].label


def test_review_requires_notes_and_filters_the_model_output(env):
    ctx, track, node, shared = _ctx(env)
    llm = FakeLLM('{"summary": "Solid start.", "went_well": ["CS 31"], "gaps": ["No projects"],'
                  f'"tracks": [{{"track_id": "{track.id}", "verdict": "ok"}}, {{"track_id": "zzz", "verdict": "x"}}],'
                  '"done_steps": [{"title": "Took CS 31", "term": "2025-fall"}, {"title": "Odd", "term": "2030-fall"}],'
                  f'"next_steps": [{{"track_id": "{track.id}", "title": "Build a project", "term": "2025-winter"}}]}}')
    with pytest.raises(ValueError):
        journey_ai.review_year(llm, ctx, 1, ["2025-fall"], {}, "2026-fall")
    out = journey_ai.review_year(llm, ctx, 1, ["2025-fall", "2026-winter"],
                                 {"2025-fall": "took CS 31"}, "2026-fall")
    assert [d["term"] for d in out["done_steps"]] == ["2025-fall", ""]
    assert out["next_steps"][0]["term"] == "2026-fall"  # never planned into the past
    assert [t["track_id"] for t in out["tracks"]] == [track.id]
    assert "took CS 31" in llm.last_user


def test_review_api_queues_suggestions_and_saves_the_review(env):
    journey, projects, roadmaps, nodes = env
    pid = journey.setup(projects, 2025)["project_id"]
    _, others = journey.tracks(pid)
    journey.set_reflection(pid, "2025-fall", "took CS 31")
    llm = FakeLLM('{"summary": "Good.", "done_steps": [{"title": "Took CS 31", "term": "2025-fall"}],'
                  f'"next_steps": [{{"track_id": "{others[0].id}", "title": "Join a lab", "term": "2026-winter"}}]}}')

    data = journey_api.handle_review(journey, projects, llm, None, {"year": 1}, TODAY)

    assert {s["title"] for s in data["suggestions"]} == {"Took CS 31", "Join a lab"}
    assert data["reviews"]["1"]["body"]["summary"] == "Good."
    assert "error" in journey_api.handle_review(journey, projects, llm, None, {"year": 4}, TODAY)


def test_evidence_only_marks_steps_that_exist(env):
    ctx, track, node, shared = _ctx(env)
    found = journey_ai.parse_evidence({"suggestions": [
        {"kind": "mark_done", "node_id": node.id, "reason": "solved 5"},
        {"kind": "mark_done", "node_id": "ghost"},
        {"kind": "add_done", "title": "Hackathon", "term": "2026-fall", "track_id": track.id},
        {"kind": "bogus", "title": "x"},
    ]}, ctx)
    assert [(f["kind"], f["title"]) for f in found] == [("mark_done", "LeetCode prep"), ("add_done", "Hackathon")]


def test_takeout_json_and_html_keep_prompts_only_and_dedupe():
    as_json = ('[{"title": "Prompted compare vector and list", "time": "2025-11-03T10:00:00Z"},'
               '{"title": "Used Gemini", "time": "2025-11-04T10:00:00Z"},'
               '{"title": "Prompted Compare vector and list", "time": "2025-11-05T10:00:00Z"}]')
    assert [(p.date, p.text) for p in parse_takeout(as_json)] == [("2025-11-03", "compare vector and list")]

    as_html = ('<div class="outer-cell"><div class="content-cell mdl-cell">Prompted what is a hash map'
               '<br>Nov 3, 2025, 10:00:00 AM PST<br>Products: Gemini Apps</div></div>')
    assert [(p.date, p.text) for p in parse_takeout(as_html)] == [("2025-11-03", "what is a hash map")]
    with pytest.raises(ValueError):
        parse_takeout("hello")


def test_gemini_import_only_reads_prompts_newer_than_last_time(env):
    journey, projects, *_ = env
    journey.setup(projects, 2025)
    state = journey._state
    llm = FakeLLM('{"suggestions": []}')
    takeout = ('[{"title": "Prompted hashing", "time": "2025-11-03T10:00:00Z"},'
               '{"title": "Prompted graphs", "time": "2025-12-03T10:00:00Z"}]')

    first = journey_api.handle_import_gemini(journey, None, llm, state, {"text": takeout})
    second = journey_api.handle_import_gemini(journey, None, llm, state, {"text": takeout})

    assert (first["found"], first["new"], first["looked_at"]) == (2, 2, 2)
    assert (second["new"], second["looked_at"]) == (0, 0)


def test_suggestions_skip_steps_already_on_a_track(env):
    journey, projects, roadmaps, nodes = env
    pid = journey.setup(projects, 2025)["project_id"]
    _, others = journey.tracks(pid)
    nodes.add(others[0].id, "Take CS 161", status="rejected", term="2026-fall")

    assert journey.add_suggestion(pid, "review", "add_step", "take cs 161", term="2026-fall") is None
    assert journey.add_suggestion(pid, "review", "add_step", "Take CS 161", term="2027-fall") is not None
    # the seeded recruiting anchor for that fall is already there
    assert journey.add_suggestion(pid, "gmail", "add_step", "Apply for summer internships",
                                  term="2026-fall") is None


def test_create_track_action_carries_its_starting_steps(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    reply, actions = journey_ai.parse_chat(
        '{"reply": "ok", "actions": [{"type": "create_track", "name": "Research", "goal": "Join a lab",'
        '"steps": [{"title": "Email professors", "term": "2027-winter"}, {"title": "", "term": "x"},'
        '{"title": "Read two papers", "term": "bad"}]}]}', ctx)
    assert actions[0].label == 'New track "Research" with 2 steps'

    res = journey_api.handle_apply(journey, {"action": {"type": "create_track", "name": "Research",
                                                       "goal": "Join a lab",
                                                       "steps": [dict(s) for s in actions[0].steps]}})

    steps = nodes.for_roadmap(res["track_id"])
    assert [(s.title, s.term, s.status) for s in steps] == [
        ("Email professors", "2027-winter", "accepted"), ("Read two papers", "", "accepted")]
    assert res["changed"] == [s.id for s in steps]


def test_calendar_events_parse_and_become_suggestions(env):
    from mindtrail.integrations.calendar_events import CalendarEvents, parse_event
    from mindtrail.integrations.google_api import GoogleAuthError

    assert parse_event({"status": "cancelled", "summary": "x", "start": {"date": "2026-11-02"}}) is None
    assert parse_event({"summary": "  ", "start": {"date": "2026-11-02"}}) is None
    midterm = parse_event({"summary": "CS 161  Midterm", "start": {"date": "2026-11-02"}})
    assert (midterm.date, midterm.title, midterm.all_day) == ("2026-11-02", "CS 161 Midterm", True)
    timed = parse_event({"summary": "Interview", "start": {"dateTime": "2026-11-04T10:00:00-08:00"}})
    assert timed.all_day is False and timed.date.startswith("2026-11")

    journey, projects, *_ = env
    journey.setup(projects, 2025)
    llm = FakeLLM('{"suggestions": [{"kind": "add_step", "title": "Prep for CS 161 midterm", '
                  '"term": "2026-fall", "reason": "Midterm on Nov 2"}]}')

    class FakeCreds(CalendarEvents):
        def between(self, start, end, limit=100):
            return [midterm]

    out = journey_api.handle_scan_calendar(journey, None, llm, FakeCreds(), TODAY)
    assert out == {"added": 1, "looked_at": 1}
    assert "2026-11-02: CS 161 Midterm (all day)" in llm.last_user
    assert journey.pending(journey.settings()["project_id"])[0].source == "calendar"

    class Disconnected(CalendarEvents):
        def between(self, start, end, limit=100):
            raise GoogleAuthError("Google isn't connected")

    assert "isn't connected" in journey_api.handle_scan_calendar(journey, None, llm, Disconnected(), TODAY)["error"]


def test_calendar_between_asks_for_the_window_and_drops_cancelled(monkeypatch):
    from datetime import date as d
    from mindtrail.integrations import calendar_events

    monkeypatch.setattr(calendar_events, "credentials_for", lambda *a, **k: ("creds", "path"))
    seen = {}

    def fake_get(creds, path, url, params):
        seen.update(url=url, params=params)
        return {"items": [{"summary": "Hackathon", "start": {"date": "2026-11-14"}},
                          {"summary": "Gone", "status": "cancelled", "start": {"date": "2026-11-15"}}]}

    got = calendar_events.CalendarEvents(get=fake_get).between(d(2026, 10, 25), d(2026, 12, 24))

    assert [e.title for e in got] == ["Hackathon"]
    assert seen["params"]["singleEvents"] == "true" and seen["params"]["timeMin"].startswith("2026-10-25")
    assert seen["params"]["timeMax"].startswith("2026-12-24")
