"""Habits: streak rules, check-in limits, and what the views receive."""

from datetime import date, timedelta

import pytest

from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import connect, initialize
from mindtrail.organize.habits import HabitStore, streak, this_week_count
from mindtrail.organize.life_data import dump_tables, load_tables
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.web import api, life_api

THU = date(2026, 10, 1)  # a Thursday


def days(*offsets):
    return {THU + timedelta(days=o) for o in offsets}


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def habits(db):
    return HabitStore(db)


# --- streak math --------------------------------------------------------------


def test_daily_streak_counts_back_from_today():
    assert streak(days(0, -1, -2), 7, THU) == 3


def test_an_unchecked_today_does_not_break_a_daily_streak():
    assert streak(days(-1, -2), 7, THU) == 2


def test_a_missed_yesterday_breaks_it():
    assert streak(days(0, -2, -3), 7, THU) == 1
    assert streak(days(-2, -3), 7, THU) == 0


def test_weekly_streak_counts_weeks_that_hit_the_target():
    # Target 2/week. This week (Mon Sep 28-) has 1 so far: not yet counted,
    # but not broken. Sep 21-27 and Sep 14-20 each hit 2; Sep 7-13 hit 1.
    done = days(-1, -4, -6, -13, -15, -21)
    assert streak(done, 2, THU) == 2


def test_weekly_streak_includes_this_week_once_hit():
    done = days(0, -1, -4, -6)
    assert streak(done, 2, THU) == 2


def test_this_week_count_starts_monday():
    assert this_week_count(days(0, -3, -4), THU) == 2  # Thu, Mon; Sun is last week


# --- store --------------------------------------------------------------------


def test_toggle_logs_then_unlogs(habits):
    h = habits.create("Read 20 min")
    assert habits.toggle(h.id, THU, THU) is True
    assert habits.toggle(h.id, THU, THU) is False
    assert habits.logs_since(THU) == {}


def test_only_the_last_week_can_be_checked(habits):
    h = habits.create("ARC")
    habits.toggle(h.id, THU - timedelta(days=7), THU)
    with pytest.raises(ValueError):
        habits.toggle(h.id, THU - timedelta(days=8), THU)
    with pytest.raises(ValueError):
        habits.toggle(h.id, THU + timedelta(days=1), THU)


def test_target_must_be_one_to_seven(habits):
    with pytest.raises(ValueError):
        habits.create("x", target_per_week=0)
    with pytest.raises(ValueError):
        habits.create("x", target_per_week=8)


def test_archived_habits_are_hidden_by_default(habits):
    h = habits.create("Old")
    habits.update(h.id, {"archived": True})
    assert habits.all() == []
    assert [x.id for x in habits.all(include_archived=True)] == [h.id]


def test_deleting_a_habit_deletes_its_logs(db, habits):
    h = habits.create("x")
    habits.toggle(h.id, THU, THU)
    habits.delete(h.id)
    with connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM habit_logs").fetchone()[0] == 0


# --- handlers and summary -------------------------------------------------------


def test_list_reports_streak_and_trims_logs_to_the_heatmap(habits):
    h = habits.create("Sleep by 1am")
    for o in range(0, 7):
        habits.toggle(h.id, THU - timedelta(days=o), THU)
    with connect(habits._path) as conn:  # an old log far outside the heatmap
        conn.execute("INSERT INTO habit_logs VALUES (?, ?)", (h.id, "2025-01-01"))

    (item,) = life_api.handle_list_habits(habits, today=THU)["habits"]
    assert (item["streak"], item["unit"], item["done_today"]) == (7, "day", True)
    assert "2025-01-01" not in item["logs"] and len(item["logs"]) == 7


def test_toggle_handler_rejects_bad_dates(habits):
    h = habits.create("x")
    assert "error" in life_api.handle_toggle_habit(habits, h.id, {"date": "yesterday"}, THU)
    assert life_api.handle_toggle_habit(habits, h.id, {}, THU) == {"logged": True,
                                                                    "date": THU.isoformat()}


def test_daily_summary_lists_habits_without_making_the_day_non_empty(db, habits):
    habits.create("Stretch")
    data = api.handle_daily_summary(ProjectStore(db), ConversationStore(db), RoadmapStore(db),
                                    RoadmapNodeStore(db), habits=habits)
    assert [h["name"] for h in data["habits"]] == ["Stretch"]
    assert data["empty"] is True


def test_habits_survive_the_backup_round_trip(tmp_path, db, habits):
    h = habits.create("ARC", target_per_week=3)
    habits.toggle(h.id, THU, THU)
    fresh = str(tmp_path / "fresh.db")
    initialize(fresh)
    load_tables(fresh, dump_tables(db), overwrite=False)
    assert dump_tables(fresh)["habit_logs"] == [{"habit_id": h.id, "date": THU.isoformat()}]
