"""The journey: setup, tracks, reflections, suggestions, and the API on top."""

import json
from dataclasses import asdict
from datetime import date

import pytest

from mindtrail.advice import journey_ai, step_fill
from mindtrail.integrations.gemini_takeout import parse_takeout
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize
from mindtrail.organize.habits import HabitStore
from mindtrail.organize.journey import JourneyStore
from mindtrail.organize.journey_chats import JourneyChatStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore, duplicate_roadmap
from mindtrail.web import journey_api, life_api, step_tasks_api
from mindtrail.web import today as today_view

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
    assert [r.name for r in others] == ["School", "AI/ML", "SWE", "Product Eng", "From career"]
    assert len(roadmaps.list_for_project(career.id)) == 1  # original untouched
    assert [n.title for n in nodes.for_roadmap(src.id)] == ["Step one"]


def test_a_second_journey_opens_and_the_first_stays_selectable(env):
    journey, projects, *_ = env
    career = journey.setup(projects, 2025)
    health = journey.setup(projects, 2025, name="Health", purpose="Run a half marathon", kind="general")

    assert journey.settings()["project_id"] == health["project_id"]
    _, paths = journey.tracks(health["project_id"])
    assert [(r.name, r.goal) for r in paths] == [("Main path", "Run a half marathon")]
    assert [j["project_id"] for j in journey.all()] == [career["project_id"], health["project_id"]]

    journey.select(career["project_id"])
    assert journey.settings()["kind"] == "career"
    with pytest.raises(ValueError):
        journey.select("nope")
    with pytest.raises(ValueError):
        journey.setup(projects, 2025, kind="general")  # a non-career journey needs a name


def test_a_database_with_one_journey_reads_it_as_the_career_journey(env):
    journey, projects, *_ = env
    p = projects.create("CS journey 2025–2029")
    journey._state.set("journey", {"project_id": p.id, "start_year": 2025})

    assert journey.all() == [{"kind": "career", "purpose": "", "project_id": p.id, "start_year": 2025}]
    added = journey.setup(projects, 2026, name="Health", kind="general")
    assert [j["project_id"] for j in journey.all()] == [p.id, added["project_id"]]


def test_deleting_the_open_journey_falls_back_to_another(env):
    journey, projects, *_ = env
    first = journey.setup(projects, 2025)
    second = journey.setup(projects, 2025, name="Health", kind="general")
    projects.delete(second["project_id"])
    assert journey.settings()["project_id"] == first["project_id"]


def test_update_renames_and_changes_purpose(env):
    journey, projects, *_ = env
    pid = journey.setup(projects, 2025, name="Health", purpose="old", kind="general")["project_id"]
    journey.update(projects, pid, name="Fitness", purpose="Bench 225")
    assert projects.get(pid).name == "Fitness"
    assert journey.settings()["purpose"] == "Bench 225"
    with pytest.raises(ValueError):
        journey.update(projects, pid, name="  ")


def test_the_model_sees_what_the_journey_is_for(env):
    journey, projects, *_ = env
    saved = journey.setup(projects, 2025, name="Health", purpose="Run a half marathon", kind="general")
    shared, paths = journey.tracks(saved["project_id"])
    ctx = journey_ai.build_context(2025, "2026-fall", shared, paths, {}, purpose=saved["purpose"],
                                   kind="general")
    assert "Run a half marathon" in ctx.text and "CS degree" not in ctx.text


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


def test_reply_never_claims_a_change_that_is_only_proposed(env):
    ctx, track, node, shared = _ctx(env)
    action = f'{{"type": "add_step", "track_id": "{track.id}", "title": "Stretch", "term": "2027-fall"}}'

    proposed, _ = journey_ai.parse_chat(
        '{"reply": "I\'ve added a stretch step. I moved nothing else, and I have put it in fall.",'
        f'"actions": [{action}]}}', ctx)
    chatting, _ = journey_ai.parse_chat('{"reply": "Last week you said you added a stretch.",'
                                        '"actions": []}', ctx)

    assert proposed == ("I've proposed adding a stretch step. I've proposed moving nothing else, "
                        "and I've proposed putting it in fall.")
    assert chatting == "Last week you said you added a stretch."


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


def test_the_api_lists_journeys_and_switches_between_them(env):
    journey, projects, *_ = env
    journey_api.handle_setup(journey, projects, {"start_year": 2025})
    data = journey_api.handle_setup(journey, projects, {"start_year": 2025, "name": "Health",
                                                        "purpose": "Sleep 8 hours", "kind": "general"})
    assert [j["name"] for j in data["journeys"]] == ["CS journey 2025–2029", "Health"]
    assert data["name"] == "Health" and data["kind"] == "general" and data["purpose"] == "Sleep 8 hours"

    switched = journey_api.handle_select(journey, projects, {"project_id": data["journeys"][0]["project_id"]})
    assert switched["kind"] == "career"
    assert "error" in journey_api.handle_select(journey, projects, {"project_id": "nope"})
    renamed = journey_api.handle_update(journey, projects, {"name": "Career"})
    assert renamed["name"] == "Career"


# --- the assistant's saved chats ------------------------------------------------


class ChatLLM:
    """Proposes adding a step to whichever track id it's told to use."""

    def __init__(self, track_id=""):
        self.track_id = track_id
        self.prompts = []

    def complete(self, system, user, max_tokens=800):
        import json as _json

        from mindtrail.llm import Completion

        self.prompts.append(user)
        actions = ([{"type": "add_step", "track_id": self.track_id, "title": "Run 5k", "term": ""}]
                   if self.track_id else [])
        return Completion(text=_json.dumps({"reply": "Sure.", "actions": actions}), tokens=1, model="stub")


def _chat_env(env):
    from mindtrail.organize.journey_chats import JourneyChatStore

    journey, projects, *_ = env
    return journey, projects, JourneyChatStore(journey._path)


def test_a_first_message_starts_a_named_chat_and_later_ones_see_its_history(env):
    journey, projects, chats = _chat_env(env)
    journey.setup(projects, 2025, name="Health", kind="general")
    llm = ChatLLM()

    first = journey_api.handle_chat(journey, chats, llm, None, {"message": "plan my running"})["chat"]
    journey_api.handle_chat(journey, chats, llm, None, {"message": "and sleep?", "chat_id": first["id"]})

    saved = chats.get(first["id"])
    assert saved["title"] == "plan my running"
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant", "user", "assistant"]
    assert "plan my running" in llm.prompts[1]


def test_each_journey_keeps_its_own_chats(env):
    journey, projects, chats = _chat_env(env)
    career = journey.setup(projects, 2025)["project_id"]
    chat = journey_api.handle_chat(journey, chats, ChatLLM(), None, {"message": "hi"})["chat"]
    journey.setup(projects, 2025, name="Health", kind="general")

    assert journey_api.handle_chats(journey, chats)["chats"] == []
    assert "error" in journey_api.handle_get_chat(journey, chats, chat["id"])
    journey.select(career)
    assert [c["id"] for c in journey_api.handle_chats(journey, chats)["chats"]] == [chat["id"]]


def test_editing_a_proposal_relabels_it_and_a_bad_edit_is_refused(env):
    journey, projects, chats = _chat_env(env)
    pid = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]
    _, paths = journey.tracks(pid)
    chat = journey_api.handle_chat(journey, chats, ChatLLM(paths[0].id), None, {"message": "add one"})["chat"]

    edited = journey_api.handle_chat_action(journey, chats, None, chat["id"],
                                            {"message": 1, "action": 0, "fields": {"title": "Run 10k"}})
    bad = journey_api.handle_chat_action(journey, chats, None, chat["id"],
                                         {"message": 1, "action": 0, "fields": {"title": ""}})
    accepted = journey_api.handle_chat_action(journey, chats, None, chat["id"],
                                              {"message": 1, "action": 0, "resolved": "accepted"})

    action = edited["chat"]["messages"][1]["actions"][0]
    assert action["title"] == "Run 10k" and "Run 10k" in action["label"]
    assert "error" in bad
    assert accepted["chat"]["messages"][1]["actions"][0]["resolved"] == "accepted"


def test_the_journey_list_carries_what_its_boxes_show(env):
    journey, projects, roadmaps, nodes = env
    pid = journey.setup(projects, 2025, name="Health", purpose="Run a half", kind="general")["project_id"]
    _, paths = journey.tracks(pid)
    nodes.add(paths[0].id, "Run 5k", status="done")
    nodes.add(paths[0].id, "Run 10k", status="accepted")
    nodes.add(paths[0].id, "Skip", status="rejected")

    box = journey_api.handle_get(journey, projects, TODAY)["journeys"][0]

    assert box["paths"] == ["Main path"] and box["purpose"] == "Run a half"
    assert (box["steps"], box["done"]) == (2, 1)


def test_older_career_journeys_get_a_school_path_once(env):
    journey, projects, roadmaps, _ = env
    pid = journey.setup(projects, 2025)["project_id"]
    school = journey.school_track(pid)
    roadmaps.delete(school.id)  # as if made before School was a default
    journey._state.set("journeySchoolAdded", [])

    journey.add_school_paths()
    added = journey.school_track(pid)
    roadmaps.delete(added.id)   # the user deletes it
    journey.add_school_paths()

    assert added is not None
    assert journey.school_track(pid) is None, "a deleted School path must stay deleted"


def test_dropping_a_step_saves_the_terms_new_order(env):
    journey, projects, roadmaps, nodes = env
    pid = journey.setup(projects, 2025)["project_id"]
    track = journey.school_track(pid)
    a = nodes.add(track.id, "A", term="2026-fall")
    b = nodes.add(track.id, "B", term="2026-fall")
    c = nodes.add(track.id, "C", term="2027-winter")

    res = journey_api.handle_move_step(journey, c.id, {"term": "2026-fall", "order": [b.id, c.id, a.id]})

    ordered = sorted((n for n in nodes.for_roadmap(track.id) if n.term == "2026-fall"), key=lambda n: n.position)
    assert res == {"ok": True}
    assert [n.title for n in ordered] == ["B", "C", "A"]


def test_an_order_naming_another_journeys_step_is_refused(env):
    journey, projects, roadmaps, nodes = env
    first = journey.setup(projects, 2025)["project_id"]
    stranger = nodes.add(journey.school_track(first).id, "Not yours")
    pid = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]
    _, paths = journey.tracks(pid)
    mine = nodes.add(paths[0].id, "Mine")

    res = journey_api.handle_move_step(journey, mine.id, {"term": "2026-fall", "order": [stranger.id, mine.id]})

    assert "error" in res and nodes.get(stranger.id).position == 0


def test_folders_group_journeys_and_disappear_when_emptied(env):
    journey, projects, *_ = env
    a = journey.setup(projects, 2025, name="Running", kind="general")["project_id"]
    b = journey.setup(projects, 2025, name="Sleep", kind="general")["project_id"]

    journey.set_folder(a, "  Health ")
    journey.set_folder(b, "Health")
    journey.rename_folder("Health", "Body")
    renamed = journey_api.handle_get(journey, projects, TODAY)
    journey.rename_folder("Body", "")

    assert renamed["folders"] == ["Body"]
    assert {j["folder"] for j in renamed["journeys"]} == {"Body"}
    assert journey.folders() == []


def test_the_assistant_can_make_a_journey_without_leaving_this_one(env):
    journey, projects, *_ = env
    here = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]

    res = journey_api.handle_apply(journey, {"action": {"type": "create_journey", "name": "Spanish",
                                                        "purpose": "Hold a conversation", "folder": "Learning"}},
                                   projects)

    made = next(j for j in journey.all() if j["project_id"] == res["journey_id"])
    assert journey.settings()["project_id"] == here
    assert (made["purpose"], made["folder"], made["kind"]) == ("Hold a conversation", "Learning", "general")


def test_the_assistant_can_file_this_journey_and_sees_the_others(env):
    journey, projects, *_ = env
    journey.setup(projects, 2025, name="Running", kind="general")
    journey.set_folder(journey.settings()["project_id"], "Health")
    here = journey.setup(projects, 2025, name="Sleep", kind="general")["project_id"]

    journey_api.handle_apply(journey, {"action": {"type": "set_folder", "folder": "Health"}}, projects)
    ctx = journey_api._context(journey, None, TODAY)
    action = journey_ai.revise_action({"type": "create_journey", "name": "", "purpose": "x"}, ctx)

    assert journey.settings()["folder"] == "Health" and journey.settings()["project_id"] == here
    assert "Running (folder Health)" in ctx.text and "FOLDER: Health" in ctx.text
    assert action is None, "a new journey needs a name"


def _habits(journey):
    return HabitStore(journey._path)


def _plan(ctx, node_id, subs, mode="add"):
    raw = json.dumps({"reply": "ok", "actions": [{"type": "plan_step", "node_id": node_id, "mode": mode,
                                                 "sub_steps": subs}]})
    return journey_ai.parse_chat(raw, ctx)[1][0]


def test_sub_steps_keep_their_order_and_show_as_progress_on_the_step(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    ids = [step_tasks_api.handle_add(journey, node.id, {"title": title, "due": due})["task"]["id"]
           for title, due in [("Pick 20 companies", "2026-11-12"), ("Draft resume", "not a day"),
                              ("Send applications", "2026-02-30")]]

    step_tasks_api.handle_reorder(journey, node.id, {"order": [ids[1], ids[0]]})
    step_tasks_api.handle_update(journey, ids[0], {"done": True})
    after = step_tasks_api.handle_list(journey, _habits(journey), node.id)["tasks"]
    step = next(s for t in journey_api.handle_get(journey, projects, TODAY)["tracks"]
                for s in t["steps"] if s["id"] == node.id)

    assert [t["title"] for t in after] == ["Draft resume", "Pick 20 companies", "Send applications"]
    assert [t["due"] for t in after] == ["", "2026-11-12", ""], "only real days are kept"
    assert step["progress"] == [1, 3]
    assert "error" in step_tasks_api.handle_add(journey, node.id, {"title": "  "})


def test_sub_steps_work_from_any_journey_but_not_outside_one(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    task_id = step_tasks_api.handle_add(journey, node.id, {"title": "Pick companies"})["task"]["id"]
    journey.setup(projects, 2025, name="Health", kind="general")
    loose = nodes.add(roadmaps.create("Side project", projects.create("side").id).id, "Ship it")

    ticked = step_tasks_api.handle_update(journey, task_id, {"done": True})

    assert ticked["task"]["done"] is True, "Today ticks sub-steps while another journey is open"
    assert "error" in step_tasks_api.handle_add(journey, loose.id, {"title": "Sneak"})


def test_a_plan_lands_in_date_order_after_what_the_step_has(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    journey.tasks.add(node.id, "Pick 20 companies")
    raw = ('{"reply": "Here is a plan.", "actions": ['
           f'{{"type": "plan_step", "node_id": "{node.id}", "sub_steps": ['
           '{"title": "Draft resume bullets", "detail": "Two per project", "due": "2026-11-20"},'
           '{"title": "", "due": "2026-11-21"}, {"title": "Ask Sam for a referral", "due": "soon"}]},'
           '{"type": "plan_step", "node_id": "made-up", "sub_steps": [{"title": "X"}]},'
           f'{{"type": "plan_step", "node_id": "{node.id}", "sub_steps": []}}]}}')

    reply, actions = journey_ai.parse_chat(raw, ctx)
    journey_api.handle_apply(journey, {"action": asdict(actions[0])})
    focus = journey_api._context(journey, None, TODAY, step_id=node.id)

    assert [a.type for a in actions] == ["plan_step"]
    assert actions[0].label == 'Plan "LeetCode prep": 2 sub-steps'
    assert [(t.title, t.due) for t in journey.tasks.for_node(node.id)] == [
        ("Draft resume bullets", "2026-11-20"), ("Pick 20 companies", ""), ("Ask Sam for a referral", "")]
    assert 'THEY HAVE THIS STEP OPEN: id=' + node.id in focus.text
    assert "3. [to do] Ask Sam for a referral" in focus.text


def test_redoing_a_plan_swaps_the_unfinished_sub_steps_and_keeps_the_done_ones(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    done = journey.tasks.add(node.id, "Pick 20 companies")
    journey.tasks.update(done.id, done=True)
    journey.tasks.add(node.id, "Draft cover letters")
    journey.tasks.add(node.id, "Submit everything")
    ctx = journey_api._context(journey, None, TODAY)

    redo = _plan(ctx, node.id, [{"title": "Apply to 2 a day", "due": "2026-11-12"}], mode="replace")
    journey_api.handle_apply(journey, {"action": asdict(redo)})

    assert redo.label == 'Redo the plan for "LeetCode prep": 1 sub-steps (replaces 2 unfinished)'
    assert [(t.title, t.done) for t in journey.tasks.for_node(node.id)] == [
        ("Pick 20 companies", True), ("Apply to 2 a day", False)]
    assert _plan(ctx, node.id, [{"title": "X"}], mode="sideways").mode == "add"


def test_a_daily_goal_is_a_habit_tied_to_the_step(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    habits = _habits(journey)
    raw = json.dumps({"reply": "ok", "actions": [
        {"type": "add_daily_goal", "node_id": node.id, "name": "Apply to 2 internships", "per_week": 7},
        {"type": "add_daily_goal", "node_id": node.id, "name": "Mock interview", "per_week": 40},
        {"type": "add_daily_goal", "node_id": node.id, "name": ""}]})

    actions = journey_ai.parse_chat(raw, ctx)[1]
    for a in actions:
        journey_api.handle_apply(journey, {"action": asdict(a)}, habits=habits)
    habits.toggle(habits.for_node(node.id)[0].id, TODAY, TODAY)
    page = step_tasks_api.handle_list(journey, habits, node.id, TODAY)
    listed = life_api.handle_list_habits(habits, today=TODAY)["habits"]
    focus = journey_api._context(journey, None, TODAY, step_id=node.id, habits=habits)

    assert [a.label for a in actions] == [
        'Daily goal for "LeetCode prep": Apply to 2 internships (every day)',
        'Daily goal for "LeetCode prep": Mock interview (every day)']
    assert [(g["name"], g["done_today"]) for g in page["goals"]] == [
        ("Apply to 2 internships", True), ("Mock interview", False)]
    assert {h["step"]["title"] for h in listed} == {"LeetCode prep"}
    assert "Apply to 2 internships (every day, 1-day streak, 1 this week)" in focus.text


def test_today_lists_sub_steps_due_soon_from_every_journey(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    soon = TODAY.isoformat()
    for title, due in [("Overdue", "2020-01-01"), ("Today", soon), ("Far off", "2099-01-01"), ("Undated", "")]:
        journey.tasks.add(node.id, title, due=due)
    finished = journey.tasks.add(node.id, "Finished", due=soon)
    journey.tasks.update(finished.id, done=True)
    journey.setup(projects, 2025, name="Health", kind="general")

    due = step_tasks_api.handle_due(journey, TODAY)["tasks"]

    assert [(t["title"], t["step_title"]) for t in due] == [("Overdue", "LeetCode prep"), ("Today", "LeetCode prep")]


def test_accepting_part_of_a_plan_relabels_the_card_and_titles_the_chat(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    pid = journey.settings()["project_id"]
    chats = JourneyChatStore(journey._path)
    chat = chats.create(pid)
    plan = _plan(ctx, node.id, [{"title": "A"}, {"title": "B"}, {"title": "C"}])
    chats.append_turn(chat["id"], "Plan out LeetCode prep in detail", "ok", [asdict(plan)], title="Plan: LeetCode prep")

    res = journey_api.handle_chat_action(journey, chats, None, chat["id"],
                                         {"message": 1, "action": 0, "fields": {"sub_steps": [{"title": "A"}, {"title": "C"}]}})

    card = res["chat"]["messages"][1]["actions"][0]
    assert card["label"] == 'Plan "LeetCode prep": 2 sub-steps'
    assert [s["title"] for s in card["sub_steps"]] == ["A", "C"]
    assert res["chat"]["title"] == "Plan: LeetCode prep"


def test_today_tile_counts_this_journeys_due_sub_steps_and_daily_goals(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    habits = _habits(journey)
    journey.tasks.add(node.id, "Due now", due=TODAY.isoformat())
    journey.tasks.add(node.id, "Later", due="2099-01-01")
    done_goal = habits.create("Solve one problem", node_id=node.id)
    habits.create("Read a chapter", node_id=node.id)
    habits.create("Unrelated habit")
    habits.toggle(done_goal.id, TODAY, TODAY)

    work = journey_api.handle_today(journey, projects, TODAY, habits=habits)["today"]
    listed = today_view.habits_today(habits, TODAY)

    assert work == {"due": 1, "goals_done": 1, "goals_total": 2, "step_id": node.id}
    assert {h["name"]: (h["step"] or {}).get("title") for h in listed} == {
        "Solve one problem": "LeetCode prep", "Read a chapter": "LeetCode prep", "Unrelated habit": None}


# --- the assistant can edit and delete everything ------------------------------


def _ask(ctx, *actions):
    return journey_ai.parse_chat(json.dumps({"reply": "I've changed it.", "actions": list(actions)}), ctx)


def test_the_assistant_can_edit_and_delete_sub_steps_and_daily_goals(env):
    journey, projects, roadmaps, nodes = env
    _, track, node, shared = _ctx(env)
    habits = _habits(journey)
    keep, drop = journey.tasks.add(node.id, "Draft resume"), journey.tasks.add(node.id, "Old idea")
    goal = habits.create("Solve 1 problem", 7, node_id=node.id)
    ctx = journey_api._context(journey, None, TODAY, habits=habits)

    reply, actions = _ask(ctx,
        {"type": "edit_sub_step", "task_id": keep.id, "title": "Draft resume bullets", "due": "2026-11-02",
         "done": True},
        {"type": "delete_sub_step", "task_id": drop.id},
        {"type": "edit_daily_goal", "goal_id": goal.id, "name": "Solve 2 problems", "per_week": 5},
        {"type": "delete_sub_step", "task_id": "made-up"},
        {"type": "edit_sub_step", "task_id": keep.id})
    for a in actions:
        assert "error" not in journey_api.handle_apply(journey, {"action": asdict(a)}, habits=habits)

    assert reply == "I've proposed changing it."
    assert [a.label for a in actions] == [
        'Sub-step "Draft resume": rename to "Draft resume bullets", due 2026-11-02, mark done',
        'Delete sub-step "Old idea"',
        'Daily goal "Solve 1 problem": rename to "Solve 2 problems", 5x a week']
    [task] = journey.tasks.for_node(node.id)
    assert (task.title, task.due, task.done) == ("Draft resume bullets", "2026-11-02", True)
    assert (habits.get(goal.id).name, habits.get(goal.id).target_per_week) == ("Solve 2 problems", 5)


def test_the_assistant_can_rename_steps_and_paths_and_delete_a_path(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    _, others = journey.tracks(journey.settings()["project_id"])
    spare = others[1]

    _, actions = _ask(ctx,
        {"type": "edit_step", "node_id": node.id, "title": "Grind LeetCode"},
        {"type": "edit_track", "track_id": track.id, "goal": "Land a SWE internship"},
        {"type": "move_term", "node_id": node.id, "track_id": spare.id},
        {"type": "delete_track", "track_id": spare.id})
    results = [journey_api.handle_apply(journey, {"action": asdict(a)}) for a in actions]

    assert [a.label for a in actions][:2] == ['Step "LeetCode prep": rename to "Grind LeetCode"',
                                              f"Path {track.name}: goal: Land a SWE internship"]
    assert not any("error" in r for r in results)
    assert nodes.get(node.id) is None   # it moved to the path that was then deleted
    assert roadmaps.get(track.id).goal == "Land a SWE internship"


def test_on_the_journeys_page_it_sees_every_journey_and_must_name_one(env):
    journey, projects, roadmaps, nodes = env
    career = journey.setup(projects, 2025)["project_id"]
    health = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]
    journey.select(career)
    _, paths = journey.tracks(health)
    run = nodes.add(paths[0].id, "Long run")
    ctx = journey_api._home_context(journey, None, today=TODAY)

    _, actions = _ask(ctx,
        {"type": "edit_journey", "journey_id": health, "purpose": "Run a half marathon"},
        {"type": "set_folder", "folder": "Body"},                      # no journey named: dropped
        {"type": "set_folder", "journey_id": health, "folder": "Body"},
        {"type": "edit_step", "node_id": run.id, "detail": "10 miles easy"})
    for a in actions:
        assert "error" not in journey_api.handle_apply(journey, {"action": asdict(a)}, projects)

    assert ctx.home and f"id={health}" in ctx.text and "Long run" in ctx.text
    assert [a.label for a in actions][0] == "Journey Health: for: Run a half marathon"
    assert len(actions) == 3
    saved = next(j for j in journey.all() if j["project_id"] == health)
    assert (saved["purpose"], saved["folder"]) == ("Run a half marathon", "Body")
    assert nodes.get(run.id).detail == "10 miles easy"
    assert journey.settings()["project_id"] == career   # nothing switched journeys


def test_deleting_a_journey_from_the_assistant_removes_it(env):
    journey, projects, *_ = env
    keep = journey.setup(projects, 2025)["project_id"]
    gone = journey.setup(projects, 2025, name="Old", kind="general")["project_id"]
    ctx = journey_api._home_context(journey, None, today=TODAY)

    [action] = _ask(ctx, {"type": "delete_journey", "journey_id": gone})[1]
    res = journey_api.handle_apply(journey, {"action": asdict(action)}, projects)

    assert action.label == "Delete the journey Old and everything in it"
    assert res["deleted_journey"] == gone
    assert [j["project_id"] for j in journey.all()] == [keep]


def test_home_chats_are_kept_apart_from_a_journeys_own_chats(env):
    journey, projects, *_ = env
    journey.setup(projects, 2025, name="Health", kind="general")
    own, home = JourneyChatStore(journey._path), JourneyChatStore(journey._path, table="home_chats")
    llm = ChatLLM()

    made = journey_api.handle_chat(journey, home, llm, None, {"message": "hi", "scope": "home"})["chat"]

    assert made["project_id"] == "home"
    assert journey_api.handle_chats(journey, own)["chats"] == []
    assert [c["id"] for c in journey_api.handle_chats(journey, home, "home")["chats"]] == [made["id"]]
    assert "error" in journey_api.handle_get_chat(journey, home, made["id"])   # not without the scope


# --- what it knows about you --------------------------------------------------


class _Profile:
    def __init__(self, content=""):
        self.content = content

    def get(self):
        return self

    def save(self, content):
        self.content = content


def test_facts_about_you_can_be_remembered_corrected_and_forgotten(env):
    journey, projects, *_ = env
    journey.setup(projects, 2025)
    profile = _Profile("CS student at UCI\n\nTargeting PM roles\n")
    ctx = journey_api._home_context(journey, profile, today=TODAY)

    _, actions = _ask(ctx,
        {"type": "remember", "fact": "Runs 3x a week"},
        {"type": "remember", "fact": "CS student at UCI"},               # already known: dropped
        {"type": "edit_fact", "fact_no": 2, "fact": "Targeting AI engineer roles"},
        {"type": "forget", "fact_no": 9})                                # no such fact: dropped
    for a in actions:
        journey_api.handle_apply(journey, {"action": asdict(a)}, profile=profile)

    assert "1. CS student at UCI" in ctx.text
    assert [a.label for a in actions] == [
        "Remember: Runs 3x a week", 'Change "Targeting PM roles" to "Targeting AI engineer roles"']
    # Only the changed line moves; the blank line they wrote stays.
    assert profile.content == "CS student at UCI\n\nTargeting AI engineer roles\nRuns 3x a week"


def test_a_stale_fact_edit_is_refused_rather_than_changing_the_wrong_line(env):
    journey, projects, *_ = env
    journey.setup(projects, 2025)
    profile = _Profile("Likes mornings")
    [forget] = _ask(journey_api._home_context(journey, profile, today=TODAY),
                    {"type": "forget", "fact_no": 1})[1]
    profile.save("Likes evenings")

    res = journey_api.handle_apply(journey, {"action": asdict(forget)}, profile=profile)

    assert "error" in res and profile.content == "Likes evenings"


def test_a_long_fact_reaches_the_assistant_whole(env):
    journey, projects, *_ = env
    journey.setup(projects, 2025)
    paragraph = "I study CS at UCI. " * 30

    ctx = journey_api._home_context(journey, _Profile(paragraph), today=TODAY)

    assert paragraph.strip() in ctx.text


def test_on_the_journeys_page_each_proposal_names_its_journey(env):
    journey, projects, roadmaps, nodes = env
    journey.setup(projects, 2025)
    health = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]
    _, paths = journey.tracks(health)
    run = nodes.add(paths[0].id, "Long run")
    habits = _habits(journey)
    goal = habits.create("Stretch", 7, node_id=run.id)
    ctx = journey_api._home_context(journey, None, habits=habits, today=TODAY)

    _, actions = _ask(ctx, {"type": "log_daily_goal", "goal_id": goal.id},
                      {"type": "set_term_note", "journey_id": health, "term": "2026-fall", "note": "Ran a 10k"},
                      {"type": "delete_step", "node_id": run.id})
    for a in actions:
        assert "error" not in journey_api.handle_apply(journey, {"action": asdict(a)}, habits=habits)

    assert [a.label for a in actions] == ['Check off daily goal "Stretch" for today (Health)',
                                          "Note for Fall 2026 in Health: Ran a 10k",
                                          'Delete "Long run" (Health)']
    assert journey.reflections(health) == {"2026-fall": "Ran a 10k"}
    assert habits.logs_since(date.today())[goal.id] == {date.today()}


def test_a_malformed_proposal_is_an_error_not_a_dropped_connection(env):
    journey, projects, *_ = env
    journey.setup(projects, 2025)

    res = journey_api.handle_apply(journey, {"action": {"type": "plan_step", "node_id": 5, "sub_steps": ["a"]}})

    assert "error" in res


# --- path maps: journeys that don't run on school terms -----------------------


def test_a_journey_that_isnt_school_is_a_path_map_until_switched(env):
    journey, projects, *_ = env
    career = journey.setup(projects, 2025)["project_id"]
    health = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]

    before = {j["project_id"]: j["layout"] for j in journey_api.handle_get(journey, projects, TODAY)["journeys"]}
    journey_api.handle_set_layout(journey, {"project_id": health, "layout": "terms"})
    bad = journey_api.handle_set_layout(journey, {"project_id": health, "layout": "spiral"})

    assert before == {career: "terms", health: "map"}
    assert journey_api.handle_get(journey, projects, TODAY)["layout"] == "terms"
    assert "error" in bad


def test_a_path_map_runs_in_order_and_new_steps_join_the_end(env):
    journey, projects, roadmaps, nodes = env
    pid = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]
    _, [path] = journey.tracks(pid)
    add = lambda title, **kw: journey_api.handle_add_step(journey, {"track_id": path.id, "title": title, **kw})["step"]
    shoes, five_k = add("Buy shoes"), add("Run a 5k", due="2026-11-20")
    journey_api.handle_move_step(journey, five_k["id"], {"term": "", "order": [five_k["id"], shoes["id"]]})
    nodes.set_status(five_k["id"], "done")
    half = add("Half marathon")

    data = journey_api.handle_get(journey, projects, TODAY)
    [track] = [t for t in data["tracks"] if t["id"] == path.id]
    ctx = journey_api._context(journey, None, TODAY)

    assert [s["title"] for s in journey_api._in_order(track["steps"])] == ["Run a 5k", "Buy shoes", "Half marathon"]
    assert [s["title"] for s in data["next_up"]] == ["Buy shoes"]
    assert data["next_up"][0]["reason"] == "Next stop"
    assert ctx.text.index("Run a 5k") < ctx.text.index("Buy shoes") < ctx.text.index(half["title"])
    assert "by 2026-11-20: Run a 5k" in ctx.text and "CURRENT TERM" not in ctx.text
    assert journey_api.handle_today(journey, projects, TODAY)["label"] == "All paths"


def test_the_assistant_can_date_steps_and_switch_a_journeys_layout(env):
    journey, projects, roadmaps, nodes = env
    pid = journey.setup(projects, 2025, name="Health", kind="general")["project_id"]
    _, [path] = journey.tracks(pid)
    step = nodes.add(path.id, "Long run")
    ctx = journey_api._context(journey, None, TODAY)

    _, actions = _ask(ctx,
        {"type": "add_step", "track_id": path.id, "title": "Race day", "due": "2027-03-14"},
        {"type": "edit_step", "node_id": step.id, "due": "2026-12-01"},
        {"type": "set_layout", "layout": "terms"},
        {"type": "set_layout", "layout": "zigzag"})
    for a in actions:
        assert "error" not in journey_api.handle_apply(journey, {"action": asdict(a)}, projects)

    assert [a.label for a in actions] == ['Add "Race day" to Main path, due 2027-03-14',
                                          'Step "Long run": due 2026-12-01', "Show this journey as school terms"]
    assert nodes.get(step.id).due_date == "2026-12-01"
    assert journey_api.handle_get(journey, projects, TODAY)["layout"] == "terms"


def test_with_auto_apply_the_reply_can_say_what_it_did_but_deletions_stay_proposals(env):
    ctx, track, node, shared = _ctx(env)
    add = {"type": "add_step", "track_id": track.id, "title": "Box jumps"}
    delete = {"type": "delete_step", "node_id": node.id}
    said = lambda *actions, auto: journey_ai.parse_chat(
        json.dumps({"reply": "I've added it.", "actions": list(actions)}), ctx, auto)[0]

    assert said(add, auto=True) == "I've added it."
    assert said(add, auto=False) == "I've proposed adding it."
    assert said(add, delete, auto=True) == "I've proposed adding it."


def test_auto_apply_is_told_to_the_model_only_when_on(env):
    ctx, *_ = _ctx(env)

    class Spy:
        system = ""

        def complete(self, system, user, max_tokens=800):
            from mindtrail.llm import Completion
            Spy.system = system
            return Completion(text='{"reply": "ok", "actions": []}', tokens=1, model="m")

    journey_ai.journey_chat(Spy(), ctx, [], "plan it", auto=True)
    on = Spy.system
    journey_ai.journey_chat(Spy(), ctx, [], "plan it")

    assert "APPLY AT ONCE" in on and "APPLY AT ONCE" not in Spy.system


def test_the_assistant_can_ask_one_question_with_choices_and_remembers_asking(env):
    journey, projects, chats = _chat_env(env)
    journey.setup(projects, 2025, name="Dunking", kind="general")

    class Coach:
        prompts = []

        def complete(self, system, user, max_tokens=800):
            from mindtrail.llm import Completion
            Coach.prompts.append(user)
            ask = {"question": "What's your vertical right now?", "input": "number", "unit": "inches",
                   "choices": ["Under 15 in", "15-20 in", "", "I'm not sure", "a", "b", "c", "d"]}
            return Completion(text=json.dumps({"reply": "Let's find your starting point.", "actions": [],
                                               "ask": ask}), tokens=1, model="m")

    first = journey_api.handle_chat(journey, chats, Coach(), None, {"message": "help me start"})["chat"]
    journey_api.handle_chat(journey, chats, Coach(), None, {"message": "15-20 in", "chat_id": first["id"]})
    ask = first["messages"][-1]["ask"]

    assert ask["question"] == "What's your vertical right now?"
    assert ask["choices"][:3] == ["Under 15 in", "15-20 in", "I'm not sure"] and len(ask["choices"]) == 6
    assert (ask["input"], ask["unit"]) == ("number", "inches")
    assert "[You asked: What's your vertical right now? Choices: Under 15 in / 15-20 in" in Coach.prompts[1]


def test_a_plan_waits_for_the_answer_to_a_question_asked_in_the_same_reply(env):
    ctx, track, node, shared = _ctx(env)
    reply = json.dumps({"reply": "Which kind?", "ask": {"question": "Which kind of internship?",
                                                          "choices": ["SWE", "AI/ML"]},
                        "actions": [{"type": "add_daily_goal", "node_id": node.id, "name": "Apply to one", "per_week": 7},
                                    {"type": "remember", "fact": "Wants summer 2027 internships"}]})

    _, actions, ask = journey_ai.journey_chat(FakeLLM(reply), ctx, [], "suggest daily goals")

    assert ask["question"] == "Which kind of internship?"
    assert [a.type for a in actions] == ["remember"], "goals come after the answer; facts are kept now"


def test_matching_documents_reach_the_model_with_a_reminder_to_use_them(env):
    ctx, track, node, shared = _ctx(env)
    llm = FakeLLM('{"reply": "ok", "actions": []}')

    journey_ai.journey_chat(llm, ctx, [], "plan it", notes="\n\nFROM THEIR SAVED DOCUMENTS AND NOTES: resume")

    assert "FROM THEIR SAVED DOCUMENTS AND NOTES: resume" in llm.last_user
    assert llm.last_user.rstrip().endswith(journey_ai.PERSONAL_REMINDER.strip())


def test_a_button_hint_reaches_the_assistant_but_not_the_saved_chat(env):
    journey, projects, chats = _chat_env(env)
    journey.setup(projects, 2025, name="Health", kind="general")
    llm = FakeLLM('{"reply": "ok", "actions": []}')

    chat = journey_api.handle_chat(journey, chats, llm, None, {"message": "Suggest daily goals",
                                                               "hint": "Ask me first if anything is missing."})["chat"]

    assert "Suggest daily goals Ask me first if anything is missing." in llm.last_user
    assert chat["messages"][0]["content"] == "Suggest daily goals"


def test_a_reply_without_a_question_has_no_ask(env):
    assert journey_ai.parse_ask('{"reply": "ok", "actions": []}') is None
    assert journey_ai.parse_ask('{"reply": "ok", "ask": {"question": "How tall are you?"}}')["input"] == "text"


# --- steps finish themselves; sub-steps can ask for a result; goals have a scope ---


def test_finishing_the_last_sub_step_finishes_the_step_and_unticking_reopens_it(env):
    journey, projects, roadmaps, nodes = env
    _, track, node, shared = _ctx(env)
    a, b = journey.tasks.add(node.id, "Warm up"), journey.tasks.add(node.id, "Jump")

    first = step_tasks_api.handle_update(journey, a.id, {"done": True})
    last = step_tasks_api.handle_update(journey, b.id, {"done": True})
    status_after_last = nodes.get(node.id).status
    undo = step_tasks_api.handle_update(journey, b.id, {"done": False})

    assert (first["step"], last["step"], undo["step"]) == ("", "done", "reopened")
    assert status_after_last == "done" and nodes.get(node.id).status == "accepted"


def test_a_sub_step_that_asks_for_a_result_cant_be_ticked_off_without_one(env):
    journey, projects, roadmaps, nodes = env
    _, track, node, shared = _ctx(env)
    measure = journey.tasks.add(node.id, "Measure your vertical", needs="Vertical jump", unit="in")

    refused = step_tasks_api.handle_update(journey, measure.id, {"done": True})
    taken = step_tasks_api.handle_update(journey, measure.id, {"done": True, "result": "18"})
    ctx = journey_api._context(journey, None, TODAY)

    assert refused == {"error": "Enter your vertical jump first"}
    assert taken["task"]["result"] == "18" and taken["step"] == "done"
    assert "Measure your vertical [records Vertical jump (in): 18]" in ctx.text


def test_the_assistant_plans_sub_steps_that_ask_for_results_and_records_them(env):
    journey, projects, roadmaps, nodes = env
    _, track, node, shared = _ctx(env)
    ctx = journey_api._context(journey, None, TODAY)
    plan = _plan(ctx, node.id, [{"title": "Measure your vertical", "needs": "Vertical jump", "unit": "in"}])
    journey_api.handle_apply(journey, {"action": asdict(plan)})
    [task] = journey.tasks.for_node(node.id)
    ctx = journey_api._context(journey, None, TODAY)

    _, [record] = _ask(ctx, {"type": "edit_sub_step", "task_id": task.id, "result": "18", "done": True})
    journey_api.handle_apply(journey, {"action": asdict(record)})

    assert "asks for Vertical jump (in), not entered yet" in ctx.text
    assert record.label == 'Sub-step "Measure your vertical": result 18, mark done'
    assert journey.tasks.get(task.id).result == "18" and nodes.get(node.id).status == "done"


def test_daily_goals_can_serve_a_step_a_path_or_the_whole_journey(env):
    journey, projects, roadmaps, nodes = env
    _, track, node, shared = _ctx(env)
    habits = _habits(journey)
    for scope, name in (("step", "Film 3 jumps"), ("path", "Warm up"), ("journey", "Sleep 8 hours")):
        step_tasks_api.handle_add_goal(journey, habits, node.id, {"name": name, "scope": scope})

    page = step_tasks_api.handle_list(journey, habits, node.id, TODAY)
    on_journey = step_tasks_api.handle_journey_goals(journey, habits, TODAY)
    film = next(g for g in page["goals"] if g["name"] == "Film 3 jumps")
    step_tasks_api.handle_goal_scope(journey, habits, film["id"], {"scope": "path", "track_id": track.id})

    assert [(g["name"], g["scope"]["kind"]) for g in page["goals"]] == [
        ("Film 3 jumps", "step"), ("Warm up", "path"), ("Sleep 8 hours", "journey")]
    assert [g["name"] for g in on_journey["goals"]] == ["Sleep 8 hours", "Warm up"]
    assert habits.get(film["id"]).track_id == track.id and not habits.get(film["id"]).node_id
    assert {s["kind"] for s in habits.steps().values()} == {"path", "journey"}


def test_the_assistant_puts_a_routine_on_the_path_and_can_move_a_goal(env):
    journey, projects, roadmaps, nodes = env
    _, track, node, shared = _ctx(env)
    habits = _habits(journey)
    stuck = habits.create("Stretch", 7, node_id=node.id)
    ctx = journey_api._context(journey, None, TODAY, habits=habits)

    _, actions = _ask(ctx,
        {"type": "add_daily_goal", "track_id": track.id, "name": "Warm up", "per_week": 7},
        {"type": "add_daily_goal", "name": "Sleep 8 hours", "per_week": 7},
        {"type": "edit_daily_goal", "goal_id": stuck.id, "journey_id": journey.settings()["project_id"]},
        {"type": "add_daily_goal", "track_id": "made-up", "name": "Nope"})
    for a in actions:
        assert "error" not in journey_api.handle_apply(journey, {"action": asdict(a)}, habits=habits)

    assert [a.label for a in actions] == [
        f"Daily goal for the {track.name} path: Warm up (every day)",
        "Daily goal for the whole journey: Sleep 8 hours (every day)",
        f'Daily goal "Stretch": move to {journey.names()[journey.settings()["project_id"]]}']
    assert [h.name for h in habits.for_track(track.id)] == ["Warm up"]
    assert sorted(h.name for h in habits.for_journey(journey.settings()["project_id"])) == ["Sleep 8 hours", "Stretch"]


# --- AI fill-in on a step's page ---------------------------------------------------

class DownLLM:
    def complete(self, system, user, max_tokens=900):
        from mindtrail.llm import LLMError
        raise LLMError("out for today")


def test_typed_sub_step_is_filled_out_from_the_step_it_is_on(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    llm = FakeLLM('{"title": "Measure vertical jump", "detail": "Chalk your fingers, jump, measure the mark.",'
                  ' "needs": "Vertical jump", "unit": "in", "due": "2026-10-16"}')

    res = step_tasks_api.handle_add(journey, node.id, {"title": "measure jump by friday", "fill": True},
                                    llm, TODAY)

    assert res["filled"] is True
    assert {k: res["task"][k] for k in ("title", "needs", "unit", "due")} == {
        "title": "Measure vertical jump", "needs": "Vertical jump", "unit": "in", "due": "2026-10-16"}
    assert "LeetCode prep" in llm.last_user and "measure jump by friday" in llm.last_user


def test_a_filled_sub_step_drops_past_or_fake_dates_and_units_without_a_result():
    for due in ("2026-10-12", "2026-02-30", "friday"):
        made = step_fill.parse_sub_step({"title": "Stretch", "unit": "min", "due": due}, "stretch", TODAY)
        assert made["due"] == "", due
        assert made["unit"] == "", "a unit means nothing without something to record"
    assert step_fill.parse_sub_step({}, "stretch", TODAY)["title"] == "stretch"


def test_a_filled_goal_keeps_how_often_in_range_and_never_spans_a_path_from_a_shared_step():
    assert step_fill.parse_goal({"name": "Jump rope", "per_week": 12, "scope": "path"}, "x", False) == {
        "name": "Jump rope", "per_week": 7, "scope": "path"}
    assert step_fill.parse_goal({"per_week": 0, "scope": "path"}, "jump rope", True) == {
        "name": "jump rope", "per_week": 1, "scope": "step"}
    assert step_fill.parse_goal({"per_week": "often", "scope": "everything"}, "x", False)["per_week"] == 7
    assert step_fill.parse_goal({"scope": "everything"}, "x", False)["scope"] == "step"


def test_a_typed_goal_is_filled_out_with_how_often_and_what_it_serves(env):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)
    llm = FakeLLM('{"name": "Stretch hamstrings", "per_week": 3, "scope": "journey"}')

    res = step_tasks_api.handle_add_goal(journey, _habits(journey), node.id,
                                         {"name": "stretch 3x a week", "fill": True}, llm)

    assert res["filled"] is True
    assert (res["goal"]["name"], res["goal"]["target_per_week"]) == ("Stretch hamstrings", 3)
    assert res["goal"]["journey_id"] == track.project_id


@pytest.mark.parametrize("llm", [DownLLM(), FakeLLM("sorry, no JSON here")])
def test_when_the_ai_cannot_help_what_they_typed_is_saved_as_is(env, llm):
    journey, projects, roadmaps, nodes = env
    ctx, track, node, shared = _ctx(env)

    task = step_tasks_api.handle_add(journey, node.id, {"title": "measure jump", "fill": True}, llm, TODAY)
    goal = step_tasks_api.handle_add_goal(journey, _habits(journey), node.id, {"name": "stretch", "fill": True}, llm)

    assert (task["filled"], task["task"]["title"]) == (False, "measure jump")
    assert (goal["filled"], goal["goal"]["name"], goal["goal"]["target_per_week"]) == (False, "stretch", 7)
    assert goal["goal"]["node_id"] == node.id
