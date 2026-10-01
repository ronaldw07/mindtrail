"""Today's life additions (tasks, deadlines, top priority) and the
cached automatic brief."""

from datetime import date, datetime, timedelta

import pytest

from mindtrail.advice.daily_brief import CACHE_KEY, REFRESH_MIN_SECONDS, cached_brief
from mindtrail.llm import Completion, LLMError
from mindtrail.organize.app_state import AppState
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.jobs import JobStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.organize.tasks import TaskStore
from mindtrail.web import api
from mindtrail.web.today import open_tasks, pick_top_priority, upcoming_deadlines

TODAY = date.today()


def iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


class StubLLM:
    def __init__(self, text="Do the IBM prep first.", error=None):
        self.text, self.error, self.calls = text, error, 0

    def complete(self, system, user, max_tokens=900):
        self.calls += 1
        self.last_prompt = user
        if self.error:
            raise self.error
        return Completion(text=self.text, tokens=1, model="stub")


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def s(db):
    class Stores:
        projects, chats = ProjectStore(db), ConversationStore(db)
        roadmaps, nodes = RoadmapStore(db), RoadmapNodeStore(db)
        jobs, tasks, state = JobStore(db), TaskStore(db), AppState(db)
    return Stores


def summary(s):
    return api.handle_daily_summary(s.projects, s.chats, s.roadmaps, s.nodes,
                                    None, s.tasks, s.jobs)


def test_open_tasks_keep_this_week_and_overdue_with_company(s):
    app = s.jobs.create("IBM")
    s.tasks.add("late", iso(-2))
    s.tasks.add("record", iso(1), application_id=app.id)
    s.tasks.add("far", iso(30))
    s.tasks.add("undated")
    done = s.tasks.add("done", iso(0))
    s.tasks.update(done.id, {"done": True})

    items = open_tasks(s.tasks, s.jobs, TODAY)
    assert [(i["title"], i["bucket"], i["company"]) for i in items] == [
        ("late", "overdue", ""), ("record", "this_week", "IBM")]


def test_deadlines_only_for_unapplied_applications_this_week(s):
    s.jobs.create("Google", role="APM", stage="saved", deadline=iso(2))
    s.jobs.create("Applied Co", stage="applied", deadline=iso(2))
    s.jobs.create("Missed", stage="saved", deadline=iso(-1))
    s.jobs.create("Far", stage="saved", deadline=iso(20))
    (d,) = upcoming_deadlines(s.jobs, TODAY)
    assert d["title"] == "Apply to Google (APM)"


def test_top_priority_order():
    step_today = {"title": "step", "bucket": "today", "due_date": iso(0)}
    task_overdue = {"title": "task", "bucket": "overdue", "due_date": iso(-1)}
    deadline_soon = {"title": "apply", "due_date": iso(2)}
    deadline_later = {"title": "apply later", "due_date": iso(6)}
    unblocked = {"title": "next", "due_date": ""}

    pick = lambda **kw: pick_top_priority(kw, TODAY)
    assert pick(due=[step_today], tasks=[task_overdue])["title"] == "task"
    assert pick(due=[step_today], deadlines=[deadline_soon])["kind"] == "step"
    assert pick(deadlines=[deadline_soon], unblocked=[unblocked])["kind"] == "deadline"
    assert pick(deadlines=[deadline_later], unblocked=[unblocked])["kind"] == "step"
    assert pick() is None


def test_summary_includes_tasks_and_deadlines_and_is_not_empty(s):
    s.tasks.add("Prep STAR stories", iso(0))
    data = summary(s)
    assert data["tasks"][0]["title"] == "Prep STAR stories"
    assert data["top_priority"]["kind"] == "task"
    assert data["empty"] is False


def test_summary_without_life_stores_still_works(s):
    data = api.handle_daily_summary(s.projects, s.chats, s.roadmaps, s.nodes)
    assert data["tasks"] == [] and data["empty"] is True and data["top_priority"] is None


# --- cached brief -----------------------------------------------------------

NOW = datetime.now().astimezone()


def test_unchanged_day_is_served_from_cache_without_a_model_call(s):
    s.tasks.add("Prep", iso(0))
    llm = StubLLM()
    first = cached_brief(llm, summary(s), s.state, NOW)
    second = cached_brief(llm, summary(s), s.state, NOW + timedelta(hours=3))
    assert first["text"] == second["text"] == "Do the IBM prep first."
    assert llm.calls == 1 and second["stale"] is False


def test_changes_within_the_window_reuse_the_old_brief_until_forced(s):
    s.tasks.add("Prep", iso(0))
    llm = StubLLM()
    cached_brief(llm, summary(s), s.state, NOW)
    s.tasks.add("Another", iso(0))
    soon = NOW + timedelta(seconds=REFRESH_MIN_SECONDS - 60)
    assert cached_brief(llm, summary(s), s.state, soon)["stale"] is True
    assert llm.calls == 1
    cached_brief(llm, summary(s), s.state, soon, force=True)
    assert llm.calls == 2


def test_changes_after_the_window_regenerate(s):
    s.tasks.add("Prep", iso(0))
    llm = StubLLM()
    cached_brief(llm, summary(s), s.state, NOW)
    s.tasks.add("Another", iso(0))
    later = cached_brief(llm, summary(s), s.state, NOW + timedelta(seconds=REFRESH_MIN_SECONDS + 1))
    assert llm.calls == 2 and later["stale"] is False
    assert "Another" in llm.last_prompt


def test_model_failure_falls_back_to_the_last_brief(s):
    s.tasks.add("Prep", iso(0))
    cached_brief(StubLLM(), summary(s), s.state, NOW)
    s.tasks.add("Another", iso(0))
    result = cached_brief(StubLLM(error=LLMError("down")), summary(s), s.state,
                          NOW, force=True)
    assert result["text"] == "Do the IBM prep first." and result["error"]


def test_empty_day_needs_no_model_call(s):
    llm = StubLLM()
    assert cached_brief(llm, summary(s), s.state, NOW) == {"text": "", "empty": True}
    assert llm.calls == 0


def test_handler_uses_the_cache(s):
    s.tasks.add("Prep", iso(0))
    llm = StubLLM()
    for _ in range(3):
        result = api.handle_daily_brief(s.projects, s.chats, s.roadmaps, s.nodes, llm,
                                        None, s.tasks, s.jobs, s.state)
    assert result["text"] == "Do the IBM prep first." and llm.calls == 1
    assert s.state.get(CACHE_KEY)["text"] == "Do the IBM prep first."


# --- evening wind-down ------------------------------------------------------


def test_finished_today_lists_tasks_checked_off_since_local_midnight(s):
    from mindtrail.organize.db import connect
    from mindtrail.web.today import finished_today, local_day_start_utc
    done = s.tasks.add("Done today")
    s.tasks.update(done.id, {"done": True})
    old = s.tasks.add("Done yesterday")
    s.tasks.update(old.id, {"done": True})
    with connect(s.tasks._path) as conn:
        conn.execute("UPDATE tasks SET done_at = ? WHERE id = ?",
                     ("2000-01-01T00:00:00+00:00", old.id))
    assert [t["title"] for t in finished_today(s.tasks, s.jobs, TODAY)] == ["Done today"]
    assert local_day_start_utc(TODAY).endswith("+00:00")


def test_roll_over_moves_only_open_tasks_due_by_today(s):
    from mindtrail.web.jobs_api import handle_roll_tasks
    late = s.tasks.add("late", iso(-2))
    due = s.tasks.add("due", iso(0))
    future = s.tasks.add("future", iso(3))
    undated = s.tasks.add("undated")
    finished = s.tasks.add("finished", iso(0))
    s.tasks.update(finished.id, {"done": True})

    result = handle_roll_tasks(s.tasks, {}, TODAY)
    assert result == {"moved": 2, "to": iso(1)}
    assert [s.tasks.get(t.id).due_date for t in (late, due, future, undated, finished)] == [
        iso(1), iso(1), iso(3), "", iso(0)]
    assert "error" in handle_roll_tasks(s.tasks, {"to": iso(0)}, TODAY)
