"""Repeating to-dos: parsing "every mon" and friends, and the next date."""

from datetime import date, timedelta

import pytest

from mindtrail.organize.db import initialize
from mindtrail.organize.repeats import describe, next_due, parse_repeat, parse_task_with_repeat
from mindtrail.organize.tasks import TaskStore

FRI = date(2026, 10, 9)  # a Friday


@pytest.mark.parametrize("text, title, rule", [
    ("Water plants every mon", "Water plants", "week:1:0"),
    ("Water plants every Monday", "Water plants", "week:1:0"),
    ("Gym every other fri", "Gym", "week:2:4"),
    ("Stretch daily", "Stretch", "day:1"),
    ("Stretch every day", "Stretch", "day:1"),
    ("Review notes every 3 days", "Review notes", "day:3"),
    ("Team sync every 2 weeks", "Team sync", "week:2"),
    ("Backups weekly", "Backups", "week:1"),
    ("Budget monthly", "Budget", "month:1"),
    ("Pay rent 1st of every month", "Pay rent", "month:1:1"),
    ("Pay rent every 1st", "Pay rent", "month:1:1"),
    ("Pay rent on the 15th of each month", "Pay rent", "month:1:15"),
])
def test_repeat_phrases_become_a_rule_and_leave_the_title(text, title, rule):
    assert parse_repeat(text)[:2] == (title, rule)


@pytest.mark.parametrize("text", [
    "Plan Friday's party", "Call mom", "Read every page of chapter 3", "Email Carla tmrw",
])
def test_ordinary_titles_do_not_repeat(text):
    assert parse_repeat(text) == (text, "")


def test_first_due_date_follows_the_rule():
    assert parse_task_with_repeat("Water plants every mon", FRI) == ("Water plants", "2026-10-12", "week:1:0")
    assert parse_task_with_repeat("Gym every fri", FRI) == ("Gym", "2026-10-09", "week:1:4")
    assert parse_task_with_repeat("Stretch daily", FRI) == ("Stretch", "2026-10-09", "day:1")
    assert parse_task_with_repeat("Pay rent 1st of every month", FRI) == ("Pay rent", "2026-11-01", "month:1:1")


def test_an_explicit_date_wins_over_the_rules_first_date():
    assert parse_task_with_repeat("Water plants every mon oct 20", FRI) == ("Water plants", "2026-10-20", "week:1:0")


def test_non_repeating_input_is_unchanged():
    assert parse_task_with_repeat("Call mom tmrw", FRI) == ("Call mom", "2026-10-10", "")


@pytest.mark.parametrize("rule, last, expected", [
    ("day:1", "2026-10-09", "2026-10-10"),
    ("day:3", "2026-10-09", "2026-10-12"),
    ("week:1:0", "2026-10-05", "2026-10-12"),
    ("week:2:4", "2026-10-09", "2026-10-23"),
    ("week:1", "2026-10-09", "2026-10-16"),
    ("week:2", "2026-10-09", "2026-10-23"),
    ("month:1:1", "2026-11-01", "2026-12-01"),
    ("month:1:31", "2026-01-31", "2026-02-28"),
    ("month:1", "2026-01-31", "2026-02-28"),
    ("month:1", "2026-12-15", "2027-01-15"),
])
def test_next_due_steps_from_the_last_due_date(rule, last, expected):
    assert next_due(rule, last, date(2026, 1, 1)) == expected


def test_a_late_check_off_skips_the_missed_occurrences():
    # Daily task due Oct 1, finished on Oct 9: next is tomorrow, not Oct 2.
    assert next_due("day:1", "2026-10-01", FRI) == "2026-10-10"
    assert next_due("week:1:0", "2026-09-14", FRI) == "2026-10-12"


def test_next_due_with_no_last_date_counts_from_today():
    assert next_due("day:1", "", FRI) == "2026-10-10"


def test_rules_read_back_in_plain_words():
    assert describe("day:1") == "Every day"
    assert describe("day:3") == "Every 3 days"
    assert describe("week:1:0") == "Every Monday"
    assert describe("week:2:4") == "Every other Friday"
    assert describe("week:1") == "Every week"
    assert describe("week:2") == "Every 2 weeks"
    assert describe("month:1") == "Every month"
    assert describe("month:1:1") == "Every month on the 1st"
    assert describe("") == ""


@pytest.fixture
def tasks(tmp_path):
    db = str(tmp_path / "t.db")
    initialize(db)
    return TaskStore(db)


def test_checking_off_a_repeating_task_creates_the_next_one(tasks):
    # A future Monday, so "the next occurrence after today" is a week later
    # whenever the test runs (a past due date skips the missed ones).
    today = date.today()
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    t = tasks.add("Water plants", due_date=monday.isoformat(), repeat="week:1:0")

    tasks.update(t.id, {"done": True})

    open_tasks = tasks.open()
    assert [(x.title, x.due_date, x.repeat) for x in open_tasks] == [
        ("Water plants", (monday + timedelta(days=7)).isoformat(), "week:1:0")]


def test_unchecking_removes_the_task_it_created(tasks):
    t = tasks.add("Water plants", due_date="2026-10-05", repeat="week:1:0")
    tasks.update(t.id, {"done": True})

    tasks.update(t.id, {"done": False})

    assert [x.id for x in tasks.open()] == [t.id]


def test_checking_twice_never_makes_two_next_tasks(tasks):
    t = tasks.add("Water plants", due_date="2026-10-05", repeat="week:1:0")
    for done in (True, False, True):
        tasks.update(t.id, {"done": done})

    assert len(tasks.open()) == 1


def test_a_task_that_does_not_repeat_makes_nothing(tasks):
    t = tasks.add("One-off", due_date="2026-10-05")
    tasks.update(t.id, {"done": True})

    assert tasks.open() == []


def test_a_task_can_be_linked_to_an_application_after_the_fact(tasks, tmp_path):
    from mindtrail.organize.jobs import JobStore

    app = JobStore(str(tmp_path / "t.db")).create("Acme")
    t = tasks.add("Prep")

    assert tasks.update(t.id, {"application_id": app.id}).application_id == app.id
    assert tasks.update(t.id, {"application_id": None}).application_id is None
    with pytest.raises(ValueError):
        tasks.update(t.id, {"application_id": "nope"})
