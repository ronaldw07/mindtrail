"""Roadmap and node CRUD. Pure SQLite, no network or API key."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mindtrail.organize.db import SCHEMA, initialize
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


def test_new_node_has_no_linked_entries_by_default(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X")

    assert node.linked_entries == ()


def test_linked_entries_round_trip(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", linked_entries=["e1", "e2"])

    assert nodes.get(node.id).linked_entries == ("e1", "e2")


def test_set_linked_entries_replaces_the_list(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", linked_entries=["e1"])

    nodes.set_linked_entries(node.id, ["e2", "e3"])

    assert nodes.get(node.id).linked_entries == ("e2", "e3")


def test_set_linked_entries_can_clear_it(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", linked_entries=["e1"])

    nodes.set_linked_entries(node.id, [])

    assert nodes.get(node.id).linked_entries == ()


def test_restoring_a_node_preserves_linked_entries(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", linked_entries=["e1"])
    nodes.delete(node.id)

    nodes.restore(node)

    assert nodes.get(node.id).linked_entries == ("e1",)


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


# --- recurring steps (F4) --------------------------------------------------


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _in_days(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


def test_new_node_has_no_repeat_by_default(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X")

    assert node.repeat_days == 0


def test_a_node_can_be_created_with_repeat_days(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", repeat_days=7)

    assert node.repeat_days == 7


def test_set_repeat_days_updates_it(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X")

    nodes.set_repeat_days(node.id, 14)

    assert nodes.get(node.id).repeat_days == 14


def test_set_repeat_days_rejects_negative_values(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X")

    with pytest.raises(ValueError):
        nodes.set_repeat_days(node.id, -1)


def test_marking_a_repeating_node_done_resets_to_accepted_and_advances_due_date(
    nodes, roadmap_id
):
    node = nodes.add(roadmap_id, "X", status="accepted", repeat_days=7)

    nodes.set_status(node.id, "done")

    updated = nodes.get(node.id)
    assert updated.status == "accepted"
    assert updated.due_date == _in_days(7)


def test_a_non_repeating_node_still_goes_to_done(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", status="accepted")

    nodes.set_status(node.id, "done")

    assert nodes.get(node.id).status == "done"


def test_repeat_days_zero_behaves_exactly_like_no_repeat(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "X", status="accepted", repeat_days=0)

    nodes.set_status(node.id, "done")

    assert nodes.get(node.id).status == "done"


def test_completing_an_overdue_repeating_node_schedules_from_today_not_the_stale_date(
    nodes, roadmap_id
):
    stale_due = _in_days(-30)  # a month overdue
    node = nodes.add(
        roadmap_id, "X", status="accepted", repeat_days=7, due_date=stale_due
    )

    nodes.set_status(node.id, "done")

    updated = nodes.get(node.id)
    # Anchored on today (today + 7), not on the stale due date (stale + 7),
    # which would still read as overdue the moment it comes back.
    assert updated.due_date == _in_days(7)
    assert updated.due_date > _today()


def test_node_without_repeat_days_column_loads_with_default(tmp_path):
    """Simulates a database that predates this column - the read path
    (_to_node) must guard for its absence the same way it already does
    for due_date and linked_entries, rather than raising a KeyError."""
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)  # base schema only - no ADDED_COLUMNS applied
    conn.execute(
        "INSERT INTO roadmap_nodes "
        "(id, roadmap_id, title, detail, status, note, x, y, depends_on, created_at) "
        "VALUES ('n1', 'r1', 'Old node', '', 'accepted', '', 0, 0, '', '2020-01-01')"
    )
    conn.commit()
    conn.close()

    node = RoadmapNodeStore(path).get("n1")

    assert node is not None
    assert node.repeat_days == 0
