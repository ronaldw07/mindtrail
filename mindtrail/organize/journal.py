"""The daily journal, and its copy in memory so chat can recall it.

The journal table is the source of truth. Each non-empty day is mirrored
into MemoryStore as one entry of kind "journal" (topic = the date), so
"when did I last feel burnt out?" finds it like any other note. That copy
is rebuilt from the table rather than exported - see reindex_all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mindtrail.organize.db import connect, now_iso

JOURNAL_KIND = "journal"
MAX_BODY_CHARS = 20000


@dataclass(frozen=True)
class JournalEntry:
    date: str
    body: str
    mood: int
    energy: int
    entry_id: str
    updated_at: str


def _to_entry(row) -> JournalEntry:
    return JournalEntry(date=row["date"], body=row["body"], mood=row["mood"],
                        energy=row["energy"], entry_id=row["entry_id"],
                        updated_at=row["updated_at"])


def _rating(value) -> int:
    rating = int(value or 0)
    if not 0 <= rating <= 5:
        raise ValueError("ratings are 1 to 5")
    return rating


def memory_text(entry: JournalEntry) -> tuple[str, str]:
    """(query, summary) for the memory copy."""
    day = date.fromisoformat(entry.date)
    query = f"Journal - {day.strftime('%A, %B')} {day.day}, {day.year}"
    ratings = []
    if entry.mood:
        ratings.append(f"mood {entry.mood}/5")
    if entry.energy:
        ratings.append(f"energy {entry.energy}/5")
    prefix = ("Felt " + ", ".join(ratings) + ".\n\n") if ratings else ""
    return query, prefix + entry.body.strip()


class JournalStore:
    def __init__(self, path: str | None = None, memory=None):
        self._path = path
        self._memory = memory  # MemoryStore, or None to skip the recall copy

    def get(self, day: str) -> JournalEntry | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM journal WHERE date = ?", (day,)).fetchone()
        return _to_entry(row) if row else None

    def recent(self, limit: int = 60) -> list[JournalEntry]:
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM journal ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_to_entry(r) for r in rows]

    def between(self, start: str, end: str) -> list[JournalEntry]:
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM journal WHERE date BETWEEN ? AND ? ORDER BY date", (start, end)
            ).fetchall()
        return [_to_entry(r) for r in rows]

    def save(self, day: str, body: str, mood=0, energy=0) -> JournalEntry:
        date.fromisoformat(day)
        if len(body) > MAX_BODY_CHARS:
            raise ValueError("journal entry is too long")
        mood, energy = _rating(mood), _rating(energy)
        existing = self.get(day)
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO journal (date, body, mood, energy, entry_id, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(date) DO UPDATE SET "
                "body = excluded.body, mood = excluded.mood, energy = excluded.energy, "
                "updated_at = excluded.updated_at",
                (day, body, mood, energy, existing.entry_id if existing else "", now_iso()),
            )
        return self._sync(self.get(day))

    def _set_entry_id(self, day: str, entry_id: str) -> None:
        with connect(self._path) as conn:
            conn.execute("UPDATE journal SET entry_id = ? WHERE date = ?", (entry_id, day))

    def _sync(self, entry: JournalEntry) -> JournalEntry:
        """Bring the memory copy in line with the row: add, update, or
        remove it. A no-op without a MemoryStore."""
        if self._memory is None:
            return entry
        has_copy = bool(entry.entry_id) and self._memory.get(entry.entry_id) is not None
        if not entry.body.strip():
            if has_copy:
                self._memory.delete_entry(entry.entry_id)
            self._set_entry_id(entry.date, "")
            return self.get(entry.date)
        query, summary = memory_text(entry)
        if has_copy:
            self._memory.update_entry(entry.entry_id, summary=summary, query=query)
            return entry
        created = self._memory.add(query, summary, [], topic=entry.date, kind=JOURNAL_KIND,
                                   created_at=f"{entry.date}T12:00:00+00:00")
        self._set_entry_id(entry.date, created.id)
        return self.get(entry.date)

    def reindex_all(self) -> int:
        """Recreate any missing memory copies (after an import, whose
        rows arrive without entry ids). Returns how many were added."""
        added = 0
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM journal WHERE body != ''").fetchall()
        for entry in (_to_entry(r) for r in rows):
            if entry.entry_id and self._memory.get(entry.entry_id) is not None:
                continue
            self._sync(JournalEntry(**{**entry.__dict__, "entry_id": ""}))
            added += 1
        return added
