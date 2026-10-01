"""Focus sessions: time actually spent, per day and per life area."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from mindtrail.organize.db import connect

MIN_MINUTES = 1
MAX_MINUTES = 180


@dataclass(frozen=True)
class FocusSession:
    id: str
    started_at: str
    minutes: int
    label: str
    task_id: str
    area_id: str


def _to_session(row) -> FocusSession:
    return FocusSession(id=row["id"], started_at=row["started_at"], minutes=row["minutes"],
                        label=row["label"], task_id=row["task_id"], area_id=row["area_id"])


class FocusStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def log(self, started_at: str, minutes: int, label: str = "", task_id: str = "",
            area_id: str = "") -> FocusSession:
        minutes = int(minutes)
        if not MIN_MINUTES <= minutes <= MAX_MINUTES:
            raise ValueError(f"a session is {MIN_MINUTES} to {MAX_MINUTES} minutes")
        stamp = datetime.fromisoformat(started_at)
        if stamp.tzinfo is None:
            raise ValueError("started_at needs a timezone")
        # Stored in UTC so range queries compare as plain text.
        started = stamp.astimezone(timezone.utc).isoformat()
        session = FocusSession(id=str(uuid.uuid4()), started_at=started,
                               minutes=minutes, label=label.strip()[:120], task_id=task_id,
                               area_id=area_id)
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO focus_sessions (id, started_at, minutes, label, task_id, area_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session.id, session.started_at, session.minutes, session.label,
                 session.task_id, session.area_id),
            )
        return session

    def between(self, start_utc: str, end_utc: str) -> list[FocusSession]:
        """Sessions whose start falls in [start_utc, end_utc). Both bounds
        are UTC ISO strings in the stored format."""
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM focus_sessions WHERE started_at >= ? AND started_at < ? "
                "ORDER BY started_at", (start_utc, end_utc),
            ).fetchall()
        return [_to_session(r) for r in rows]
