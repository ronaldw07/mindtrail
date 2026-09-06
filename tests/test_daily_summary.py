"""The daily summary handler: due/overdue/unblocked/recurring roadmap
steps and a since-yesterday count, all read without touching the model."""

from datetime import date, timedelta

import pytest

from mindtrail.llm import Completion, LLMError
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.web import api


class StubLLM:
    def __init__(self, text="focus on X today", error=None):
        self._text = text
        self._error = error
        self.calls = 0

    def complete(self, system, user, max_tokens=900):
        self.calls += 1
        if self._error:
            raise self._error
        return Completion(text=self._text, tokens=5, model="stub")


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def chats(db):
    return ConversationStore(db)


@pytest.fixture
def projects(db):
    return ProjectStore(db)


@pytest.fixture
def roadmaps(db):
    return RoadmapStore(db)


@pytest.fixture
def nodes(db):
    return RoadmapNodeStore(db)


def _iso(offset_days):
    return (date.today() + timedelta(days=offset_days)).isoformat()


def test_empty_state_is_flagged_and_has_no_items(projects, chats, roadmaps, nodes):
    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    assert data["due"] == []
    assert data["unblocked"] == []
    assert data["recurring"] == []
    assert data["empty"] is True


def test_overdue_and_today_steps_land_in_due_overdue_first(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    today = nodes.add(roadmap.id, "Today step", status="accepted", due_date=_iso(0))
    overdue = nodes.add(roadmap.id, "Overdue step", status="accepted", due_date=_iso(-2))
    nodes.add(roadmap.id, "Next week", status="accepted", due_date=_iso(5))

    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    titles = [n["title"] for n in data["due"]]
    assert titles == [overdue.title, today.title]
    assert data["empty"] is False


def test_due_items_report_their_bucket_and_recurring_flag(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    nodes.add(
        roadmap.id, "Weekly review", status="accepted", due_date=_iso(0), repeat_days=7
    )

    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    assert data["due"][0]["bucket"] == "today"
    assert data["due"][0]["is_recurring"] is True


def test_unblocked_step_appears_when_dependency_is_done(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    prerequisite = nodes.add(roadmap.id, "Learn Agile", status="done")
    ready = nodes.add(roadmap.id, "Apply", status="accepted")
    nodes.set_depends_on(ready.id, [prerequisite.id])

    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    assert [n["title"] for n in data["unblocked"]] == [ready.title]
    assert data["empty"] is False


def test_blocked_step_is_not_reported_as_unblocked(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    prerequisite = nodes.add(roadmap.id, "Learn Agile", status="accepted")
    blocked = nodes.add(roadmap.id, "Apply", status="accepted")
    nodes.set_depends_on(blocked.id, [prerequisite.id])

    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    titles = [n["title"] for n in data["unblocked"]]
    assert blocked.title not in titles
    assert prerequisite.title in titles


def test_a_step_due_today_is_not_duplicated_into_unblocked(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    # Unblocked (no deps) and due today - should show up once, under "due".
    nodes.add(roadmap.id, "Apply", status="accepted", due_date=_iso(0))

    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    assert len(data["due"]) == 1
    assert data["unblocked"] == []


def test_recurring_step_coming_due_within_the_week_is_surfaced(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    step = nodes.add(
        roadmap.id, "Weekly review", status="accepted", due_date=_iso(4), repeat_days=7
    )

    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    assert [n["title"] for n in data["recurring"]] == [step.title]


def test_non_recurring_step_due_this_week_is_not_in_recurring(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    nodes.add(roadmap.id, "One-off", status="accepted", due_date=_iso(4))

    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    assert data["recurring"] == []


def test_done_and_rejected_nodes_are_excluded_from_every_section(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    nodes.add(roadmap.id, "Finished", status="done", due_date=_iso(0))
    nodes.add(roadmap.id, "Skipped", status="rejected", due_date=_iso(0))

    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    assert data["empty"] is True


def test_new_since_yesterday_counts_recent_conversations(projects, chats, roadmaps, nodes):
    chats.create("Fresh chat")

    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    assert data["new_since_yesterday"] == 1


def test_new_since_yesterday_is_zero_with_no_conversations(projects, chats, roadmaps, nodes):
    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    assert data["new_since_yesterday"] == 0


def test_project_with_no_roadmap_contributes_nothing(projects, chats, roadmaps, nodes):
    projects.create("Career")

    data = api.handle_daily_summary(projects, chats, roadmaps, nodes)

    assert data["empty"] is True


# --- handle_daily_brief: the on-demand LLM endpoint ------------------------


def test_brief_endpoint_calls_the_model_when_there_is_something_due(
    projects, chats, roadmaps, nodes
):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    nodes.add(roadmap.id, "Apply", status="accepted", due_date=_iso(0))
    llm = StubLLM(text="apply today")

    result = api.handle_daily_brief(projects, chats, roadmaps, nodes, llm)

    assert result == {"text": "apply today"}
    assert llm.calls == 1


def test_brief_endpoint_never_calls_the_model_when_summary_is_empty(
    projects, chats, roadmaps, nodes
):
    llm = StubLLM()

    result = api.handle_daily_brief(projects, chats, roadmaps, nodes, llm)

    assert "error" in result
    assert llm.calls == 0


def test_brief_endpoint_surfaces_a_friendly_rate_limit_error(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    nodes.add(roadmap.id, "Apply", status="accepted", due_date=_iso(0))
    llm = StubLLM(error=LLMError("rate limited after 5 attempts: x"))

    result = api.handle_daily_brief(projects, chats, roadmaps, nodes, llm)

    assert result == {"error": "rate limited"}
