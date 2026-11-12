"""Crossing off and archiving Today's to-dos."""

import pytest

from mindtrail.organize.db import initialize
from mindtrail.organize.today_marks import TodayMarks

TASK = {"kind": "task", "ref": "t1", "title": "Email recruiter", "sub": "Due today", "group": "other"}
ESSAY = {"kind": "assignment", "ref": "a1", "title": "Lighting essay", "group": "classes"}


@pytest.fixture
def marks(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return TodayMarks(path)


def test_a_crossed_off_to_do_stays_on_today_until_the_next_day(marks):
    marks.cross(TASK, "2026-11-10")

    same_day = marks.for_today("2026-11-10")
    next_day = marks.for_today("2026-11-11")

    assert [c["ref"] for c in same_day["crossed"]] == ["t1"] and same_day["hidden"] == []
    assert next_day["crossed"] == [] and next_day["hidden"] == ["task:t1"]
    assert [a["title"] for a in marks.archived()] == ["Email recruiter"]


def test_removing_hides_it_and_putting_it_back_restores_it(marks):
    marks.archive(ESSAY, "2026-11-10")
    assert marks.for_today("2026-11-10")["hidden"] == ["assignment:a1"]
    assert marks.archived()[0]["done_on"] == "", "removed without being done"

    marks.forget("assignment", "a1")

    assert marks.for_today("2026-11-10") == {"crossed": [], "pinned": [], "hidden": []}
    assert marks.archived() == []


def test_unchecking_brings_it_back_unstruck(marks):
    marks.cross(TASK, "2026-11-10")
    marks.uncross("task", "t1")
    assert marks.for_today("2026-11-10") == {"crossed": [], "pinned": [], "hidden": []}


def test_removing_a_done_to_do_remembers_it_was_done(marks):
    marks.cross(TASK, "2026-11-10")
    marks.archive(TASK, "2026-11-10", done=True)
    assert marks.archived()[0]["done_on"] == "2026-11-10"
    assert marks.for_today("2026-11-10")["crossed"] == []


@pytest.mark.parametrize("bad", [{**TASK, "kind": "email"}, {**TASK, "ref": " "}, {**TASK, "title": ""}])
def test_unknown_or_blank_to_dos_are_refused(marks, bad):
    with pytest.raises(ValueError):
        marks.cross(bad, "2026-11-10")


def test_three_can_be_picked_for_today_and_a_fourth_is_refused(marks):
    for n in range(3):
        marks.pin({**TASK, "ref": f"t{n}"}, "2026-11-10")

    with pytest.raises(ValueError, match="Unstar one"):
        marks.pin({**TASK, "ref": "t9"}, "2026-11-10")
    marks.pin({**TASK, "ref": "t0"}, "2026-11-10")   # re-starring one already picked is fine
    assert len(marks.for_today("2026-11-10")["pinned"]) == 3
    assert marks.for_today("2026-11-11")["pinned"] == [], "picks are for one day"


def test_unchecking_a_pick_keeps_it_picked(marks):
    marks.pin(TASK, "2026-11-10")
    marks.cross(TASK, "2026-11-10")

    marks.uncross("task", "t1")

    today = marks.for_today("2026-11-10")
    assert today["crossed"] == [] and [p["ref"] for p in today["pinned"]] == ["t1"]
    marks.unpin("task", "t1")
    assert marks.for_today("2026-11-10") == {"crossed": [], "pinned": [], "hidden": []}
