"""Roadmap and node CRUD. Pure SQLite, no network or API key."""

import pytest

from mindtrail.organize.db import initialize
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def roadmaps(db):
    return RoadmapStore(db)


@pytest.fixture
def nodes(db):
    return RoadmapNodeStore(db)


@pytest.fixture
def project_id(db):
    """A real project row, since roadmaps.project_id is a foreign key."""
    return ProjectStore(db).create("Career").id


@pytest.fixture
def roadmap_id(db, project_id):
    """A real roadmap row, since roadmap_nodes.roadmap_id is a foreign key."""
    return RoadmapStore(db).create("Goal", project_id=project_id).id


# --- roadmap ------------------------------------------------------------


def test_created_roadmap_is_retrievable(roadmaps, project_id):
    r = roadmaps.create("Become a PM", project_id=project_id)

    assert roadmaps.get(r.id).goal == "Become a PM"


def test_blank_goal_is_rejected(roadmaps):
    with pytest.raises(ValueError):
        roadmaps.create("   ")


def test_for_project_finds_the_roadmap(roadmaps, project_id):
    r = roadmaps.create("Goal", project_id=project_id)

    assert roadmaps.for_project(project_id).id == r.id


def test_for_project_returns_none_when_absent(roadmaps):
    assert roadmaps.for_project("nope") is None


def test_for_project_prefers_the_newest(roadmaps, project_id):
    roadmaps.create("Old goal", project_id=project_id)
    newer = roadmaps.create("New goal", project_id=project_id)

    assert roadmaps.for_project(project_id).id == newer.id


def test_deleting_a_missing_roadmap_raises(roadmaps):
    with pytest.raises(ValueError):
        roadmaps.delete("nope")


# --- nodes ----------------------------------------------------------------


def test_added_node_defaults_to_proposed(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "Learn Agile")

    assert node.status == "proposed"
    assert node.note == ""


def test_invalid_status_on_add_is_rejected(nodes, roadmap_id):
    with pytest.raises(ValueError):
        nodes.add(roadmap_id, "X", status="bogus")


def test_set_status_updates_it(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X")

    nodes.set_status(node.id, "accepted")

    assert nodes.get(node.id).status == "accepted"


def test_set_status_rejects_invalid_values(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X")

    with pytest.raises(ValueError):
        nodes.set_status(node.id, "bogus")


def test_set_note_is_independent_of_status(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X")

    nodes.set_note(node.id, "my private note")
    nodes.set_status(node.id, "rejected")

    updated = nodes.get(node.id)
    assert updated.note == "my private note"
    assert updated.status == "rejected"


def test_new_node_has_no_due_date_by_default(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X")

    assert node.due_date == ""


def test_a_node_can_be_created_with_a_due_date(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", due_date="2026-09-30")

    assert node.due_date == "2026-09-30"


def test_set_due_date_is_independent_of_other_fields(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", status="accepted")

    nodes.set_due_date(node.id, "2026-10-15")

    updated = nodes.get(node.id)
    assert updated.due_date == "2026-10-15"
    assert updated.status == "accepted"


def test_set_due_date_can_clear_it(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", due_date="2026-09-30")

    nodes.set_due_date(node.id, "")

    assert nodes.get(node.id).due_date == ""


def test_move_updates_position(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", x=0, y=0)

    nodes.move(node.id, 150.5, 300.25)

    moved = nodes.get(node.id)
    assert moved.x == 150.5
    assert moved.y == 300.25


def test_rename_updates_title_and_detail(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "Old", detail="old detail")

    nodes.rename(node.id, "New", "new detail")

    updated = nodes.get(node.id)
    assert updated.title == "New"
    assert updated.detail == "new detail"


def test_rename_rejects_blank_title(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X")

    with pytest.raises(ValueError):
        nodes.rename(node.id, "   ")


def test_depends_on_round_trips(nodes, roadmap_id):
    a = nodes.add(roadmap_id, "A")
    b = nodes.add(roadmap_id, "B", depends_on=[a.id])

    assert nodes.get(b.id).depends_on == (a.id,)


def test_depends_on_can_be_replaced(nodes, roadmap_id):
    a = nodes.add(roadmap_id, "A")
    b = nodes.add(roadmap_id, "B")

    nodes.set_depends_on(b.id, [a.id])

    assert nodes.get(b.id).depends_on == (a.id,)


def test_deleting_a_node_removes_it(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X")

    nodes.delete(node.id)

    assert nodes.get(node.id) is None


def test_deleting_a_missing_node_raises(nodes):
    with pytest.raises(ValueError):
        nodes.delete("nope")


def test_for_roadmap_scopes_to_that_roadmap(nodes, roadmaps, project_id):
    r1 = roadmaps.create("Goal 1", project_id=project_id)
    r2 = roadmaps.create("Goal 2", project_id=project_id)
    nodes.add(r1.id, "A")
    nodes.add(r2.id, "B")

    assert [n.title for n in nodes.for_roadmap(r1.id)] == ["A"]


def test_mutating_a_missing_node_raises(nodes):
    with pytest.raises(ValueError):
        nodes.set_status("nope", "accepted")
    with pytest.raises(ValueError):
        nodes.move("nope", 1, 1)
