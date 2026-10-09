"""Dated backups: contents, pruning, restore, and folder validation."""

import json
from datetime import date

import pytest

from mindtrail.organize.app_state import AppState
from mindtrail.organize.backup import BackupStore
from mindtrail.organize.db import connect, initialize
from mindtrail.organize.tasks import TaskStore


@pytest.fixture
def setup(tmp_path):
    db = str(tmp_path / "t.db")
    initialize(db)
    state = AppState(db)
    backups = BackupStore(db, state, keep=3)
    backups.set_folder(str(tmp_path / "bk"))
    return db, state, backups, TaskStore(db)


def test_a_run_writes_a_database_copy_and_a_life_file(setup):
    db, state, backups, tasks = setup
    tasks.add("Buy milk")

    made = backups.run(date(2026, 10, 9))

    folder = backups.folder()
    assert (folder / "mindtrail-2026-10-09.db").is_file()
    life = json.loads((folder / "life-2026-10-09.json").read_text())
    assert [t["title"] for t in life["tasks"]] == ["Buy milk"]
    assert made.db_bytes > 0 and made.life_bytes > 0


def test_the_database_copy_opens_and_holds_the_same_rows(setup):
    import sqlite3

    db, state, backups, tasks = setup
    tasks.add("Buy milk")
    backups.run(date(2026, 10, 9))

    copy = sqlite3.connect(backups.folder() / "mindtrail-2026-10-09.db")
    assert copy.execute("SELECT title FROM tasks").fetchall() == [("Buy milk",)]
    copy.close()


def test_only_the_newest_few_are_kept(setup):
    db, state, backups, tasks = setup
    for day in range(1, 6):
        backups.run(date(2026, 10, day))

    assert [b.date for b in backups.list()] == ["2026-10-05", "2026-10-04", "2026-10-03"]
    assert len(list(backups.folder().iterdir())) == 6  # 3 days x 2 files


def test_running_twice_on_one_day_keeps_one_pair(setup):
    db, state, backups, tasks = setup
    backups.run(date(2026, 10, 9))
    backups.run(date(2026, 10, 9))

    assert len(backups.list()) == 1


def test_nothing_is_due_until_backups_are_turned_on(setup):
    db, state, backups, tasks = setup

    assert not backups.due(date(2026, 10, 9))

    backups.set_enabled(True)

    assert backups.due(date(2026, 10, 9))


def test_due_until_todays_backup_has_run(setup):
    db, state, backups, tasks = setup
    backups.set_enabled(True)
    today = date(2026, 10, 9)
    assert backups.due(today)

    backups.run(today)

    assert not backups.due(today)
    assert backups.due(date(2026, 10, 10))


def test_restore_brings_back_what_was_deleted_and_keeps_what_was_added(setup):
    db, state, backups, tasks = setup
    gone = tasks.add("Deleted later")
    backups.run(date(2026, 10, 9))
    tasks.delete(gone.id)
    newer = tasks.add("Added later")

    backups.restore("2026-10-09")

    titles = {t.title for t in tasks.all()}
    assert titles == {"Deleted later", "Added later"}
    assert newer.title in titles


def test_the_canvas_link_is_never_written(setup):
    db, state, backups, tasks = setup
    state.set("canvas_ics_url", "https://secret.example/feed.ics")
    backups.run(date(2026, 10, 9))

    text = (backups.folder() / "life-2026-10-09.json").read_text()

    assert "secret.example" not in text


def test_restore_rejects_a_missing_day_and_a_path(setup):
    db, state, backups, tasks = setup

    with pytest.raises(ValueError):
        backups.restore("2026-01-01")
    with pytest.raises(ValueError):
        backups.restore("../../etc/passwd")


def test_set_folder_rejects_relative_paths_and_files(setup, tmp_path):
    db, state, backups, tasks = setup
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")

    with pytest.raises(ValueError):
        backups.set_folder("relative/dir")
    with pytest.raises(ValueError):
        backups.set_folder(str(a_file))


def test_the_database_copy_also_leaves_out_the_canvas_link(setup):
    import sqlite3

    db, state, backups, tasks = setup
    state.set("canvas_ics_url", "https://secret.example/feed.ics")
    backups.run(date(2026, 10, 9))

    copy = sqlite3.connect(backups.folder() / "mindtrail-2026-10-09.db")
    assert copy.execute("SELECT COUNT(*) FROM app_state WHERE key = 'canvas_ics_url'").fetchone() == (0,)
    copy.close()


def test_a_store_built_without_a_path_uses_the_default_database(tmp_path, monkeypatch):
    from mindtrail import config

    monkeypatch.setattr(config, "CHROMA_DIR", str(tmp_path / "chroma_data"))
    initialize()
    state = AppState()
    backups = BackupStore(None, state)
    backups.set_folder(str(tmp_path / "bk"))

    backups.run(date(2026, 10, 9))

    assert (tmp_path / "bk" / "mindtrail-2026-10-09.db").is_file()
