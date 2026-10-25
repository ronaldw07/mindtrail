"""Measure: weekly averages before/after a split, finished weeks only."""

from datetime import date

import pytest

from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize
from mindtrail.organize.tasks import TaskStore
from mindtrail.organize.timelog import TimeLogStore
from mindtrail.web import measure_api

TODAY = date(2026, 11, 30)  # a Monday; every week before it has ended


@pytest.fixture
def env(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return TimeLogStore(path), TaskStore(path), AppState(path)


def test_log_validation(env):
    log, *_ = env
    for bad in [("sleeping", 5, ""), ("planning", 0, ""), ("planning", 601, ""),
                ("planning", "x", ""), ("planning", 5, "tomorrow")]:
        with pytest.raises(ValueError):
            log.add(*bad)
    assert log.add("planning", "45", "2026-11-02", "  weekly  ").note == "weekly"


def test_the_drop_is_measured_from_finished_weeks_only(env):
    log, tasks, state = env
    log.add("planning", 60, "2026-10-05")   # baseline weeks: 100 min/week
    log.add("planning", 40, "2026-10-07")
    log.add("planning", 100, "2026-10-12")
    log.add("planning", 20, "2026-11-02")   # after: 20, 20
    log.add("planning", 20, "2026-11-10")
    log.add("planning", 5, "2026-11-30")    # this week hasn't ended: ignored

    out = measure_api.summarize(log.all(), tasks.all(), date(2026, 11, 1), TODAY)

    assert out["before"]["weeks"] == 2 and out["before"]["avg"]["planning"] == 100.0
    assert out["after"]["weeks"] == 2 and out["after"]["avg"]["planning"] == 20.0
    assert out["change"]["planning"] == 80
    assert out["change"]["refinding"] is None      # nothing logged for it


def test_a_week_with_other_logs_but_no_refinding_counts_as_zero(env):
    log, tasks, _ = env
    log.add("planning", 30, "2026-10-05")
    log.add("refinding", 20, "2026-10-12")
    out = measure_api.summarize(log.all(), tasks.all(), None, TODAY)
    assert out["before"]["weeks"] == 2
    assert out["before"]["avg"] == {"planning": 15.0, "refinding": 10.0}
    assert out["change"] == {}


def test_tasks_per_day_counts_completions_inside_the_counted_weeks(env):
    from types import SimpleNamespace

    log, *_ = env
    log.add("planning", 10, "2026-10-05")     # baseline week of Mon Oct 5
    log.add("planning", 10, "2026-11-02")     # after week of Mon Nov 2
    done = lambda day, n: [SimpleNamespace(done=True, done_at=f"{day}T12:00:00+00:00") for _ in range(n)]
    tasks = done("2026-10-06", 7) + done("2026-11-03", 14) + done("2026-09-01", 50)  # last: outside

    out = measure_api.summarize(log.all(), tasks, date(2026, 11, 1), TODAY)

    assert out["before"]["tasks_per_day"] == 1.0 and out["after"]["tasks_per_day"] == 2.0
    assert out["change"]["tasks"] == 100


def test_handlers_round_trip(env):
    log, tasks, state = env
    assert "error" in measure_api.handle_log(log, {"kind": "nope", "minutes": 5})
    made = measure_api.handle_log(log, {"kind": "planning", "minutes": 30, "day": "2026-10-05"})
    assert measure_api.handle_set_split(state, {"day": "2026-11-01"})["ok"]
    assert "error" in measure_api.handle_set_split(state, {"day": "soon"})
    data = measure_api.handle_measure(log, tasks, state, TODAY)
    assert data["split"] == "2026-11-01" and data["recent"][0]["minutes"] == 30
    assert measure_api.handle_delete_log(log, made["log"]["id"]) == {"ok": True}
    assert "error" in measure_api.handle_delete_log(log, made["log"]["id"])
