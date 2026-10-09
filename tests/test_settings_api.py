"""Settings: the connections checklist and backup handlers."""

from datetime import date

import pytest

from mindtrail.organize.app_state import AppState
from mindtrail.organize.backup import BackupStore
from mindtrail.organize.db import initialize
from mindtrail.organize.health import HealthStore
from mindtrail.organize.journal import JournalStore
from mindtrail.web import settings_api


class FakeCanvas:
    def __init__(self, url=""):
        self._url = url

    def url(self):
        return self._url


class FakeGitHub:
    def __init__(self, cached=None):
        self._cached = cached or {}

    def cached(self):
        return self._cached


@pytest.fixture
def parts(tmp_path):
    db = str(tmp_path / "t.db")
    initialize(db)
    backups = BackupStore(db, AppState(db))
    backups.set_folder(str(tmp_path / "bk"))
    return db, HealthStore(db), backups


NO_GOOGLE = {"client_configured": False, "connected": False, "calendar": False, "gmail": False, "sheets": False}
ALL_GOOGLE = {"client_configured": True, "connected": True, "calendar": True, "gmail": True, "sheets": True}


def test_nothing_connected_shows_how_to_start_each_one(parts):
    db, health, backups = parts

    out = settings_api.handle_connections(FakeCanvas(), FakeGitHub(), health, backups, lambda: NO_GOOGLE)

    assert out["done"] == 0 and out["total"] == 5
    assert "GOOGLE_CLIENT_ID" in out["checklist"][0]["detail"]


def test_everything_connected_counts_as_done(parts):
    db, health, backups = parts
    from mindtrail.organize.db import connect

    with connect(db) as conn:
        conn.execute("INSERT INTO health_sleep (date, minutes) VALUES ('2026-10-08', 420)")
    backups.set_enabled(True)
    backups.run(date(2026, 10, 9))

    out = settings_api.handle_connections(
        FakeCanvas("https://x/feed.ics"), FakeGitHub({"connected": True, "login": "me"}),
        health, backups, lambda: ALL_GOOGLE)

    assert out["done"] == 5
    assert out["checklist"][2]["detail"] == "Reading as @me"


def test_google_connected_without_gmail_asks_to_reconnect(parts):
    db, health, backups = parts
    partial = {**ALL_GOOGLE, "gmail": False}

    out = settings_api.handle_connections(FakeCanvas(), FakeGitHub(), health, backups, lambda: partial)

    assert out["checklist"][0]["done"] is False
    assert "Reconnect" in out["checklist"][0]["detail"]


def test_backup_handlers_run_list_and_restore(parts):
    db, health, backups = parts
    from mindtrail.organize.tasks import TaskStore

    tasks = TaskStore(db)
    task = tasks.add("Keep me")
    settings_api.handle_backup_run(backups, date(2026, 10, 9))
    tasks.delete(task.id)

    listed = settings_api.handle_backups(backups)
    restored = settings_api.handle_backup_restore(
        backups, JournalStore(db, None), {"date": "2026-10-09"})

    assert [b["date"] for b in listed["backups"]] == ["2026-10-09"]
    assert restored["restored"] >= 1
    assert [t.title for t in tasks.all()] == ["Keep me"]


def test_bad_folder_and_bad_date_come_back_as_errors(parts):
    db, health, backups = parts

    assert "error" in settings_api.handle_backup_folder(backups, {"path": "nope"})
    assert "error" in settings_api.handle_backup_restore(backups, JournalStore(db, None), {"date": "2020-01-01"})


def test_enabling_backups_sets_the_folder_and_turns_them_on(parts, tmp_path):
    db, health, backups = parts
    target = tmp_path / "chosen"

    out = settings_api.handle_backup_enable(
        backups, {"enabled": True, "path": str(target)}, date(2026, 10, 9))

    assert out["enabled"] is True and out["folder"] == str(target) and target.is_dir()
    assert out["last"] == "2026-10-09"
    assert settings_api.handle_backup_enable(backups, {"enabled": False})["enabled"] is False
