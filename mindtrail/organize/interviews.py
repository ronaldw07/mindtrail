"""Interview rounds for a job application: when, what kind, who, your prep
notes, and the questions you were actually asked afterwards."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from mindtrail.organize.db import connect, now_iso
from mindtrail.organize.jobs import clean_date

KINDS = ("phone", "technical", "behavioral", "onsite", "other")
MAX_TEXT = 8000
UPCOMING_DAYS = 7


@dataclass(frozen=True)
class Round:
    id: str
    application_id: str
    date: str
    kind: str
    interviewer: str
    person_id: str
    prep_notes: str
    questions: str
    created_at: str


def _to_round(row) -> Round:
    return Round(**{k: row[k] for k in row.keys()})


class InterviewStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def add(self, application_id: str, day: str = "", kind: str = "other", interviewer: str = "",
            person_id: str = "", prep_notes: str = "", questions: str = "") -> Round:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
        r = Round(id=str(uuid.uuid4()), application_id=application_id, date=clean_date(day),
                  kind=kind, interviewer=interviewer.strip()[:120], person_id=person_id or "",
                  prep_notes=prep_notes[:MAX_TEXT], questions=questions[:MAX_TEXT], created_at=now_iso())
        try:
            with connect(self._path) as conn:
                conn.execute(
                    "INSERT INTO interview_rounds (id, application_id, date, kind, interviewer, "
                    "person_id, prep_notes, questions, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    tuple(asdict(r).values()))
        except Exception as exc:  # sqlite3.IntegrityError: no such application
            raise ValueError(f"no such application: {application_id}") from exc
        return r

    def get(self, round_id: str) -> Round | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM interview_rounds WHERE id = ?", (round_id,)).fetchone()
        return _to_round(row) if row else None

    def for_application(self, application_id: str) -> list[Round]:
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM interview_rounds WHERE application_id = ? "
                "ORDER BY date = '', date, created_at", (application_id,)).fetchall()
        return [_to_round(r) for r in rows]

    def update(self, round_id: str, fields: dict) -> Round:
        current = self.get(round_id)
        if current is None:
            raise ValueError(f"no such round: {round_id}")
        changes: dict = {}
        if "date" in fields:
            changes["date"] = clean_date(fields["date"])
        if "kind" in fields:
            if fields["kind"] not in KINDS:
                raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
            changes["kind"] = fields["kind"]
        for key in ("interviewer", "person_id"):
            if key in fields:
                changes[key] = str(fields[key] or "").strip()[:120]
        for key in ("prep_notes", "questions"):
            if key in fields:
                changes[key] = str(fields[key] or "")[:MAX_TEXT]
        if changes:
            with connect(self._path) as conn:
                conn.execute(f"UPDATE interview_rounds SET {', '.join(f'{k} = ?' for k in changes)} "
                             "WHERE id = ?", (*changes.values(), round_id))
        return self.get(round_id)

    def delete(self, round_id: str) -> None:
        with connect(self._path) as conn:
            if conn.execute("DELETE FROM interview_rounds WHERE id = ?", (round_id,)).rowcount == 0:
                raise ValueError(f"no such round: {round_id}")

    def upcoming(self, today: date, days: int = UPCOMING_DAYS) -> list[dict]:
        """Rounds dated today through `days` ahead, soonest first, with the
        company name and how many days away - what Today reminds you of."""
        end = (today + timedelta(days=days)).isoformat()
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT r.*, a.company, a.role FROM interview_rounds r "
                "JOIN applications a ON a.id = r.application_id "
                "WHERE r.date != '' AND r.date >= ? AND r.date <= ? ORDER BY r.date, r.created_at",
                (today.isoformat(), end)).fetchall()
        return [{**{k: row[k] for k in row.keys()},
                 "days_away": (date.fromisoformat(row["date"]) - today).days} for row in rows]
