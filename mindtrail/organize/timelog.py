"""A log of minutes spent on things Mind Trail is meant to shorten.

Two kinds: "planning" (working out what to do next) and "refinding"
(looking for something you already researched). Logging a baseline week
done the old way, then a week with Mind Trail, is what lets the Measure
card say how much time it saved - from numbers you wrote down, not
guessed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from mindtrail.organize.db import connect, now_iso

KINDS = ("planning", "refinding")
MAX_MINUTES = 600
MAX_NOTE = 200


@dataclass(frozen=True)
class TimeLog:
    id: str
    kind: str
    minutes: int
    day: str
    note: str
    created_at: str


def _to_log(row) -> TimeLog:
    return TimeLog(**{k: row[k] for k in row.keys()})


class TimeLogStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def add(self, kind: str, minutes, day: str = "", note: str = "") -> TimeLog:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            raise ValueError("minutes must be a whole number") from None
        if not 1 <= minutes <= MAX_MINUTES:
            raise ValueError(f"minutes must be between 1 and {MAX_MINUTES}")
        day = (day or date.today().isoformat()).strip()
        try:
            date.fromisoformat(day)
        except ValueError:
            raise ValueError("day must look like 2026-10-25") from None
        log = TimeLog(id=str(uuid.uuid4()), kind=kind, minutes=minutes, day=day,
                      note=str(note or "").strip()[:MAX_NOTE], created_at=now_iso())
        with connect(self._path) as conn:
            conn.execute("INSERT INTO time_logs (id, kind, minutes, day, note, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (log.id, log.kind, log.minutes, log.day, log.note, log.created_at))
        return log

    def all(self) -> list[TimeLog]:
        """Oldest day first."""
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM time_logs ORDER BY day, created_at").fetchall()
        return [_to_log(r) for r in rows]

    def delete(self, log_id: str) -> None:
        with connect(self._path) as conn:
            if conn.execute("DELETE FROM time_logs WHERE id = ?", (log_id,)).rowcount == 0:
                raise ValueError(f"no such log: {log_id}")
