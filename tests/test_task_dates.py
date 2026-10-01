"""Natural due dates on quick-added to-dos."""

from datetime import date

import pytest

from mindtrail.organize.task_dates import parse_task_input

WED = date(2026, 9, 30)  # a Wednesday


@pytest.mark.parametrize("text,title,due", [
    ("Email Carla back fri", "Email Carla back", "2026-10-02"),
    ("Email Carla back by Friday", "Email Carla back", "2026-10-02"),
    ("Standup notes wed", "Standup notes", "2026-09-30"),
    ("Pay rent tmrw", "Pay rent", "2026-10-01"),
    ("Pay rent today", "Pay rent", "2026-09-30"),
    ("Book flights next week", "Book flights", "2026-10-05"),
    ("Dentist next fri", "Dentist", "2026-10-09"),
    ("Dentist next wed", "Dentist", "2026-10-07"),
    ("Renew lease in 3 days", "Renew lease", "2026-10-03"),
    ("Renew lease in 2 weeks", "Renew lease", "2026-10-14"),
    ("Taxes oct 12", "Taxes", "2026-10-12"),
    ("Taxes Oct. 12th", "Taxes", "2026-10-12"),
    ("Taxes 12 october", "Taxes", "2026-10-12"),
    ("Taxes 10/12", "Taxes", "2026-10-12"),
    ("Birthday card sep 1", "Birthday card", "2027-09-01"),
])
def test_trailing_dates_are_parsed(text, title, due):
    assert parse_task_input(text, WED) == (title, due)


@pytest.mark.parametrize("text", [
    "Plan Friday's party",
    "fri",
    "Read chapter 13/40 notes",
    "Feb 30",
    "Call about the 2/30 invoice",
])
def test_no_date_or_nothing_left_keeps_the_text(text):
    title, due = parse_task_input(text, WED)
    assert due == "" and title == " ".join(text.split())


def test_whitespace_is_normalized():
    assert parse_task_input("  Call   mom   tmrw ", WED) == ("Call mom", "2026-10-01")


def test_quick_add_handler_parses_the_title_unless_a_date_is_given(tmp_path):
    from mindtrail.organize.db import initialize
    from mindtrail.organize.tasks import TaskStore
    from mindtrail.web.jobs_api import handle_add_task

    db = str(tmp_path / "t.db")
    initialize(db)
    tasks = TaskStore(db)
    parsed = handle_add_task(tasks, {"title": "Call mom today"})["task"]
    assert parsed["title"] == "Call mom" and parsed["due_date"] == date.today().isoformat()
    explicit = handle_add_task(tasks, {"title": "Call mom today", "due_date": "2030-01-01"})["task"]
    assert explicit["title"] == "Call mom today" and explicit["due_date"] == "2030-01-01"
