"""The dashboard handler: cached highlights, next roadmap steps, and
recent activity, all read without touching the model."""

import pytest

from mindtrail.advice.highlights import Highlight, highlights_to_json
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.web import api


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


def test_empty_state_returns_empty_lists(projects, chats, roadmaps, nodes):
    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    assert data == {"highlights": [], "next_up": [], "recent": []}


def test_highlights_come_from_cached_advice_only(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    cached = [Highlight(headline="Apply to APM roles", detail="d", source="s")]
    projects.save_advice(project.id, highlights_to_json(cached), basis_count=1)

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    assert data["highlights"] == [
        {
            "project_id": project.id,
            "project_name": "Career",
            "headline": "Apply to APM roles",
            "priority": cached[0].priority,
        }
    ]


def test_next_up_only_includes_accepted_nodes_ordered_by_position(
    projects, chats, roadmaps, nodes
):
    project = projects.create("Career")
    roadmap = roadmaps.create("Land a PM role", project_id=project.id)
    later = nodes.add(roadmap.id, "Apply", status="accepted", x=200)
    earlier = nodes.add(roadmap.id, "Learn Agile", status="accepted", x=10)
    nodes.add(roadmap.id, "Not decided yet", status="proposed", x=5)
    nodes.add(roadmap.id, "Skipped", status="rejected", x=1)

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    titles = [n["title"] for n in data["next_up"]]
    assert titles == [earlier.title, later.title]


def test_next_up_is_capped_per_project(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    for i in range(5):
        nodes.add(roadmap.id, f"Step {i}", status="accepted", x=i)

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    assert len(data["next_up"]) == 2


def test_project_with_no_roadmap_contributes_nothing_to_next_up(
    projects, chats, roadmaps, nodes
):
    projects.create("Career")

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    assert data["next_up"] == []


def test_next_up_prefers_unblocked_steps_over_x_position(projects, chats, roadmaps, nodes):
    # x order alone would put "Apply" first (x=1); it depends on a step
    # that isn't done yet, so the genuinely actionable step should lead
    # despite its higher x.
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    prerequisite = nodes.add(roadmap.id, "Learn Agile", status="proposed", x=0)
    blocked = nodes.add(roadmap.id, "Apply", status="accepted", x=1)
    nodes.set_depends_on(blocked.id, [prerequisite.id])
    unblocked = nodes.add(roadmap.id, "Network", status="accepted", x=20)

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    titles = [n["title"] for n in data["next_up"]]
    assert titles == [unblocked.title, blocked.title]


def test_next_up_reports_whether_each_step_is_unblocked(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    prerequisite = nodes.add(roadmap.id, "Learn Agile", status="done", x=0)
    ready = nodes.add(roadmap.id, "Apply", status="accepted", x=10)
    nodes.set_depends_on(ready.id, [prerequisite.id])

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    assert data["next_up"][0]["unblocked"] is True


def test_next_up_sorts_unblocked_steps_by_soonest_due_date(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    later = nodes.add(roadmap.id, "Later", status="accepted", x=0, due_date="2026-12-01")
    sooner = nodes.add(roadmap.id, "Sooner", status="accepted", x=99, due_date="2026-09-15")

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    titles = [n["title"] for n in data["next_up"]]
    assert titles == [sooner.title, later.title]


def test_next_up_pushes_undated_steps_after_dated_ones(projects, chats, roadmaps, nodes):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    dated = nodes.add(roadmap.id, "Dated", status="accepted", x=99, due_date="2026-12-01")
    undated = nodes.add(roadmap.id, "Undated", status="accepted", x=0)

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    titles = [n["title"] for n in data["next_up"]]
    assert titles == [dated.title, undated.title]


def test_next_up_marks_a_step_with_an_unfinished_dependency_as_blocked(
    projects, chats, roadmaps, nodes
):
    project = projects.create("Career")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    prerequisite = nodes.add(roadmap.id, "Learn Agile", status="accepted", x=0)
    blocked = nodes.add(roadmap.id, "Apply", status="accepted", x=10)
    nodes.set_depends_on(blocked.id, [prerequisite.id])

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    blocked_entry = next(n for n in data["next_up"] if n["title"] == "Apply")
    assert blocked_entry["unblocked"] is False


def test_recent_includes_filed_and_unfiled_chats_with_project_names(
    projects, chats, roadmaps, nodes
):
    project = projects.create("Career")
    filed = chats.create("Resume review", project_id=project.id)
    unfiled = chats.create("Quick question")

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    by_id = {c["id"]: c for c in data["recent"]}
    assert by_id[filed.id]["project_name"] == "Career"
    assert by_id[unfiled.id]["project_name"] is None


def test_recent_is_capped(projects, chats, roadmaps, nodes):
    for i in range(12):
        chats.create(f"Chat {i}")

    data = api.handle_dashboard(projects, chats, roadmaps, nodes)

    assert len(data["recent"]) == 8
