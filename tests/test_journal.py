"""The journal: storage, its recall copy in memory, and the backup path."""

from datetime import date, timedelta

import pytest

from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.export import collect_export_files, export_to_directory
from mindtrail.organize.journal import JOURNAL_KIND, JournalStore
from mindtrail.organize.life_data import dump_tables
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.restore_apply import import_from_directory
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.web import life_api
from mindtrail.web.today import journal_today

TODAY = date(2026, 10, 1)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def memory(tmp_path):
    return MemoryStore(path=str(tmp_path / "chroma"), collection="journaltest",
                       db_path=str(tmp_path / "mem.db"))


def stores(db, memory):
    return (memory, ConversationStore(db), ProjectStore(db), RoadmapStore(db),
            RoadmapNodeStore(db), ProfileStore(db))


def test_save_upserts_one_entry_per_day(db):
    journal = JournalStore(db)
    journal.save("2026-10-01", "first", mood=3)
    journal.save("2026-10-01", "second", mood=4, energy=2)
    entry = journal.get("2026-10-01")
    assert (entry.body, entry.mood, entry.energy) == ("second", 4, 2)
    assert len(journal.recent()) == 1


def test_ratings_and_dates_are_validated(db):
    journal = JournalStore(db)
    with pytest.raises(ValueError):
        journal.save("2026-10-01", "x", mood=6)
    with pytest.raises(ValueError):
        journal.save("yesterday", "x")


def test_memory_copy_follows_the_entry_and_is_searchable(db, memory):
    journal = JournalStore(db, memory)
    journal.save("2026-09-30", "Completely burnt out after three midterms.", mood=1)
    entry_id = journal.get("2026-09-30").entry_id
    copy = memory.get(entry_id)
    assert (copy.kind, copy.topic) == (JOURNAL_KIND, "2026-09-30")
    assert "mood 1/5" in copy.summary
    assert any(r.id == entry_id for r in memory.search("burnt out midterms", k=3))

    journal.save("2026-09-30", "Actually it was fine.", mood=3)
    assert journal.get("2026-09-30").entry_id == entry_id
    assert "fine" in memory.get(entry_id).summary

    journal.save("2026-09-30", "   ")
    assert memory.get(entry_id) is None
    assert journal.get("2026-09-30").entry_id == ""


def test_backup_restores_the_journal_and_rebuilds_its_memory_copy(tmp_path, db, memory):
    journal = JournalStore(db, memory)
    journal.save("2026-09-30", "Great run at the ARC.", mood=5, energy=4)
    memory.add("A normal note", "keep me", [])

    files = {f.path: f.content for f in collect_export_files(*stores(db, memory))}
    assert "Great run" not in files["notes.md"]
    assert "entry_id" not in str(dump_tables(db)["journal"])

    out = tmp_path / "export"
    export_to_directory(*stores(db, memory), str(out))
    db2 = str(tmp_path / "b.db")
    initialize(db2)
    memory2 = MemoryStore(path=str(tmp_path / "chroma2"), collection="journaltest2",
                          db_path=str(tmp_path / "mem2.db"))
    summary = import_from_directory(str(out), *stores(db2, memory2))
    assert summary.failed == 0

    restored = JournalStore(db2, memory2).get("2026-09-30")
    assert restored.mood == 5 and restored.entry_id
    journal_copies = [e for e in memory2.all() if e.kind == JOURNAL_KIND]
    assert [e.id for e in journal_copies] == [restored.entry_id]


def test_handlers_refuse_future_days_and_rotate_prompts(db):
    journal = JournalStore(db)
    assert "error" in life_api.handle_get_journal(journal, "2026-10-02", TODAY)
    assert "error" in life_api.handle_save_journal(journal, {"date": "2026-10-02"}, TODAY)
    blank = life_api.handle_get_journal(journal, "", TODAY)
    assert blank["entry"]["body"] == "" and len(blank["prompts"]) == 2
    tomorrow = life_api.prompts_for(TODAY + timedelta(days=1))
    assert tomorrow != blank["prompts"]


def test_today_reports_written_and_the_mood_trend(db):
    journal = JournalStore(db)
    journal.save("2026-09-10", "outside the 14-day window", mood=2)
    journal.save("2026-09-29", "", mood=3)
    journal.save("2026-10-01", "today", mood=4, energy=5)
    data = journal_today(journal, TODAY)
    assert data["written_today"] is True
    assert [t["date"] for t in data["trend"]] == ["2026-09-29", "2026-10-01"]
