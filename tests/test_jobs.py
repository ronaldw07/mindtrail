"""Job applications, tasks, and their export/import round trip."""

import json

import pytest

from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import connect, initialize
from mindtrail.organize.jobs import (
    CLOSED,
    PIPELINE,
    JobStore,
    email_may_move,
    normalize_company,
)
from mindtrail.organize.life_data import dump_tables, load_tables
from mindtrail.organize.tasks import TaskStore


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def jobs(db):
    return JobStore(db)


@pytest.fixture
def tasks(db):
    return TaskStore(db)


def test_email_never_moves_a_stage_backward():
    for i, current in enumerate(PIPELINE):
        for earlier in PIPELINE[:i + 1]:
            assert not email_may_move(current, earlier)


def test_email_moves_open_stages_forward_and_can_reject():
    assert email_may_move("applied", "oa")
    assert email_may_move("applied", "interview")
    assert email_may_move("interview", "rejected")


def test_nothing_an_email_says_reopens_a_closed_or_offer_stage():
    for closed in (*CLOSED, "offer"):
        for stage in (*PIPELINE, *CLOSED):
            assert not email_may_move(closed, stage)


def test_email_cannot_withdraw_you():
    assert not email_may_move("applied", "withdrawn")


def test_company_matching_ignores_case_punctuation_and_legal_suffix():
    assert normalize_company("Stripe, Inc.") == normalize_company("stripe")
    assert normalize_company("Jane Street") != normalize_company("Jane")


def test_create_validates(jobs):
    with pytest.raises(ValueError):
        jobs.create("  ")
    with pytest.raises(ValueError):
        jobs.create("Acme", stage="ghosted")
    with pytest.raises(ValueError):
        jobs.create("Acme", deadline="next tuesday")


def test_find_matches_company_and_optional_role(jobs):
    app = jobs.create("Google LLC", role="APM Intern")
    assert jobs.find("google").id == app.id
    assert jobs.find("Google", "apm intern").id == app.id
    assert jobs.find("Google", "SWE Intern") is None


def test_advance_from_email_respects_forward_only(jobs):
    app = jobs.create("IBM", stage="interview")
    assert not jobs.advance_from_email(app.id, "applied")
    assert jobs.get(app.id).stage == "interview"
    assert jobs.advance_from_email(app.id, "offer")
    assert jobs.get(app.id).stage == "offer"


def test_manual_update_can_move_anywhere(jobs):
    app = jobs.create("IBM", stage="offer")
    assert jobs.update(app.id, {"stage": "applied"}).stage == "applied"


def test_deleting_an_application_deletes_its_tasks(jobs, tasks):
    app = jobs.create("IBM")
    tasks.add("Prep STAR stories", application_id=app.id)
    general = tasks.add("Buy groceries")
    jobs.delete(app.id)
    assert [t.id for t in tasks.all()] == [general.id]


def test_tasks_sort_dated_first_then_undated(tasks):
    undated = tasks.add("whenever")
    later = tasks.add("later", due_date="2026-12-01")
    sooner = tasks.add("sooner", due_date="2026-10-02")
    assert [t.id for t in tasks.all()] == [sooner.id, later.id, undated.id]


def test_done_sets_and_clears_timestamp(tasks):
    t = tasks.add("x")
    done = tasks.update(t.id, {"done": True})
    assert done.done and done.done_at
    undone = tasks.update(t.id, {"done": False})
    assert not undone.done and undone.done_at == ""
    assert [x.id for x in tasks.open()] == [t.id]


def test_app_state_round_trips_json(db):
    state = AppState(db)
    assert state.get("missing", 7) == 7
    state.set("k", {"a": [1, 2]})
    state.set("k", {"a": [3]})
    assert state.get("k") == {"a": [3]}


def test_life_tables_round_trip_into_an_empty_database(tmp_path, jobs, tasks, db):
    app = jobs.create("IBM", role="PM Intern", deadline="2026-10-08")
    tasks.add("Record interview", due_date="2026-10-07", application_id=app.id)
    AppState(db).set("sheet_url", "https://docs.google.com/x")

    # Through JSON text, exactly as the export file stores it.
    data = json.loads(json.dumps(dump_tables(db)))
    fresh = str(tmp_path / "fresh.db")
    initialize(fresh)
    created, skipped, failed, warnings = load_tables(fresh, data, overwrite=False)

    assert (failed, warnings) == (0, [])
    assert created == 3
    assert dump_tables(fresh) == dump_tables(db)


def test_life_import_is_idempotent_and_overwrite_updates(tmp_path, jobs, db):
    app = jobs.create("IBM")
    data = dump_tables(db)
    assert load_tables(db, data, overwrite=False)[:3] == (0, 1, 0)

    data["applications"][0]["notes"] = "edited in the export"
    load_tables(db, data, overwrite=True)
    assert jobs.get(app.id).notes == "edited in the export"


def test_life_import_reports_a_task_whose_application_is_missing(tmp_path, db):
    data = {"tasks": [{
        "id": "t1", "title": "orphan", "application_id": "nope", "created_at": "x",
    }]}
    created, skipped, failed, warnings = load_tables(db, data, overwrite=False)
    assert (created, failed) == (0, 1)
    assert warnings


def test_life_import_drops_columns_this_version_does_not_know(db):
    data = {"app_state": [{"key": "k", "value": "1", "updated_at": "x", "future": "?"}]}
    assert load_tables(db, data, overwrite=False)[0] == 1
    with connect(db) as conn:
        assert conn.execute("SELECT value FROM app_state").fetchone()["value"] == "1"
