"""Focus sessions: logging rules and the weekly roll-up."""

from datetime import date, datetime, timedelta

import pytest

from mindtrail.organize.db import initialize
from mindtrail.organize.focus import FocusStore
from mindtrail.organize.tasks import TaskStore
from mindtrail.web import life_api

THU = date(2026, 10, 1)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


def local(day: date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour).astimezone().isoformat()


def test_log_rejects_bad_lengths_and_naive_times(db):
    focus = FocusStore(db)
    with pytest.raises(ValueError):
        focus.log(local(THU, 9), 0)
    with pytest.raises(ValueError):
        focus.log(local(THU, 9), 500)
    with pytest.raises(ValueError):
        focus.log("2026-10-01T09:00:00", 25)


def test_times_are_stored_in_utc(db):
    s = FocusStore(db).log(local(THU, 9), 25)
    assert s.started_at.endswith("+00:00")


def test_session_on_a_task_takes_its_area(db):
    tasks = TaskStore(db)
    t = tasks.add("Prep", area_id="career")
    res = life_api.handle_log_focus(FocusStore(db), tasks,
                                    {"started_at": local(THU, 9), "minutes": 25, "task_id": t.id})
    assert res["session"]["area_id"] == "career"


def test_week_rolls_up_by_local_day_and_area(db):
    focus = FocusStore(db)
    focus.log(local(THU, 9), 25, area_id="career")
    focus.log(local(THU, 23), 50, area_id="school")   # late evening still counts as Thursday
    focus.log(local(THU - timedelta(days=3), 10), 25, area_id="career")  # Monday
    focus.log(local(THU - timedelta(days=4), 10), 25, area_id="career")  # last Sunday: excluded

    week = life_api.focus_week(focus, THU)
    assert week["week_start"] == "2026-09-28"
    assert week["days"] == [25, 0, 0, 75, 0, 0, 0]
    assert (week["today"], week["total"]) == (75, 100)
    assert week["by_area"] == [{"area_id": "school", "minutes": 50},
                               {"area_id": "career", "minutes": 50}] or \
           week["by_area"] == [{"area_id": "career", "minutes": 50},
                               {"area_id": "school", "minutes": 50}]
