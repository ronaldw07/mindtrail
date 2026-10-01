"""The weekly review: what counts as done, slipped, and on-target."""

from datetime import date, datetime, timedelta, timezone

import pytest

from mindtrail.llm import Completion, LLMError
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import connect, initialize
from mindtrail.organize.focus import FocusStore
from mindtrail.organize.habits import HabitStore
from mindtrail.organize.jobs import JobStore
from mindtrail.organize.journal import JournalStore
from mindtrail.organize.tasks import TaskStore
from mindtrail.web import review

THU = date(2026, 10, 1)


class StubLLM:
    def __init__(self, error=None):
        self.error, self.prompt = error, ""

    def complete(self, system, user, max_tokens=900):
        self.prompt = user
        if self.error:
            raise self.error
        return Completion(text="A solid week.", tokens=1, model="stub")


@pytest.fixture
def deps(tmp_path):
    db = str(tmp_path / "t.db")
    initialize(db)

    class Deps:
        tasks, jobs, habits = TaskStore(db), JobStore(db), HabitStore(db)
        journal, focus, state = JournalStore(db), FocusStore(db), AppState(db)
        llm = StubLLM()
    return Deps


def test_done_and_slipped(deps):
    finished = deps.tasks.add("Finished")
    deps.tasks.update(finished.id, {"done": True})
    deps.tasks.add("Slipped", "2026-09-29")
    deps.tasks.add("Due later this week", "2026-10-03")
    deps.tasks.add("Last week", "2026-09-25")

    wednesday_3pm = datetime(2026, 9, 30, 15).astimezone().astimezone(timezone.utc)
    with connect(deps.tasks._path) as conn:
        conn.execute("UPDATE tasks SET done_at = ? WHERE id = ?",
                     (wednesday_3pm.isoformat(), finished.id))

    data = review.week_review(deps.tasks, deps.jobs, deps.habits, deps.journal, deps.focus,
                              deps.state, THU)
    assert [d["title"] for d in data["done"]] == ["Finished"]
    assert [s["title"] for s in data["slipped"]] == ["Slipped"]
    assert data["week_start"] == "2026-09-28" and data["week_end"] == "2026-10-04"


def test_habit_rate_counts_daily_targets_only_for_days_elapsed(deps):
    daily = deps.habits.create("Read")
    weekly = deps.habits.create("Gym", target_per_week=3)
    for d in (0, 1, 2, 3):
        deps.habits.toggle(daily.id, THU - timedelta(days=d), THU)
    deps.habits.toggle(weekly.id, THU, THU)
    data = review.week_review(deps.tasks, deps.jobs, deps.habits, deps.journal, deps.focus,
                              deps.state, THU)
    rows = {r["name"]: (r["done"], r["target"]) for r in data["habits"]["rows"]}
    assert rows == {"Read": (4, 4), "Gym": (1, 3)}
    assert data["habits"]["rate"] == round(5 / 7, 2)


def test_previous_week_and_future_offsets(deps):
    assert review.handle_week(deps, {"offset": ["-1"]}, THU)["week_start"] == "2026-09-21"
    assert "error" in review.handle_week(deps, {"offset": ["1"]}, THU)
    assert "error" in review.handle_week(deps, {"offset": ["soon"]}, THU)


def test_priorities_are_capped_cleaned_and_monday_keyed(deps):
    bad = review.handle_save_priorities(deps.state, {"week_start": "2026-10-01", "items": []})
    assert "error" in bad
    saved = review.handle_save_priorities(deps.state, {
        "week_start": "2026-10-05", "items": ["  Apply  to Google ", "", "IBM", "x", "y"]})
    assert saved == {"items": ["Apply to Google", "IBM", "x"]}
    assert review.handle_week(deps, {}, THU)["next_priorities"] == ["Apply to Google", "IBM", "x"]


def test_summary_is_stored_and_errors_are_friendly(deps):
    deps.tasks.add("Slipped", "2026-09-29")
    assert review.handle_week_summary(deps, {}, THU) == {"text": "A solid week."}
    assert "SLIPPED: Slipped" in deps.llm.prompt
    assert review.handle_week(deps, {}, THU)["summary"] == "A solid week."
    deps.llm = StubLLM(error=LLMError("completion failed: 403"))
    assert review.handle_week_summary(deps, {}, THU) == {"error": "the model was unavailable"}
