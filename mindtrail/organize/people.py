"""People to keep in touch with, and when they're due a nudge."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from mindtrail.organize.db import connect, now_iso
from mindtrail.organize.jobs import clean_date

MAX_NUDGE_DAYS = 365


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    context: str
    notes: str
    last_contacted: str
    nudge_every_days: int
    application_id: str
    created_at: str


def _to_person(row) -> Person:
    return Person(**{k: row[k] for k in row.keys()})


def _nudge_days(value) -> int:
    days = int(value or 0)
    if not 0 <= days <= MAX_NUDGE_DAYS:
        raise ValueError(f"nudge every 0 to {MAX_NUDGE_DAYS} days")
    return days


def days_since(person: Person, today: date) -> int | None:
    if not person.last_contacted:
        return None
    return (today - date.fromisoformat(person.last_contacted)).days


def is_due(person: Person, today: date) -> bool:
    """Due once nudge_every_days have passed since you last talked - or,
    if you never logged a conversation, since you added them, so adding
    ten people doesn't put ten nudges on Today at once."""
    if not person.nudge_every_days:
        return False
    since = days_since(person, today)
    if since is None:
        added = datetime.fromisoformat(person.created_at).astimezone().date()
        since = (today - added).days
    return since >= person.nudge_every_days


class PeopleStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def create(self, name: str, context: str = "", nudge_every_days: int = 0,
               last_contacted: str = "") -> Person:
        name = name.strip()
        if not name:
            raise ValueError("name must not be empty")
        person = Person(id=str(uuid.uuid4()), name=name[:80], context=context.strip()[:160],
                        notes="", last_contacted=clean_date(last_contacted),
                        nudge_every_days=_nudge_days(nudge_every_days), application_id="",
                        created_at=now_iso())
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO people (id, name, context, notes, last_contacted, "
                "nudge_every_days, application_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (person.id, person.name, person.context, person.notes, person.last_contacted,
                 person.nudge_every_days, person.application_id, person.created_at),
            )
        return person

    def get(self, person_id: str) -> Person | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
        return _to_person(row) if row else None

    def all(self) -> list[Person]:
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM people ORDER BY LOWER(name)").fetchall()
        return [_to_person(r) for r in rows]

    def update(self, person_id: str, fields: dict) -> Person:
        if self.get(person_id) is None:
            raise ValueError(f"no such person: {person_id}")
        changes: dict = {}
        for key, limit in (("name", 80), ("context", 160), ("notes", 4000)):
            if key in fields:
                changes[key] = str(fields[key] or "").strip()[:limit]
        if "name" in changes and not changes["name"]:
            raise ValueError("name must not be empty")
        if "last_contacted" in fields:
            changes["last_contacted"] = clean_date(fields["last_contacted"])
        if "nudge_every_days" in fields:
            changes["nudge_every_days"] = _nudge_days(fields["nudge_every_days"])
        if "application_id" in fields:
            changes["application_id"] = str(fields["application_id"] or "")
        if changes:
            assignments = ", ".join(f"{k} = ?" for k in changes)
            with connect(self._path) as conn:
                conn.execute(f"UPDATE people SET {assignments} WHERE id = ?",
                             (*changes.values(), person_id))
        return self.get(person_id)

    def delete(self, person_id: str) -> None:
        with connect(self._path) as conn:
            if conn.execute("DELETE FROM people WHERE id = ?", (person_id,)).rowcount == 0:
                raise ValueError(f"no such person: {person_id}")

    def due(self, today: date) -> list[Person]:
        """People due a nudge, longest-overdue first."""
        due = [p for p in self.all() if is_due(p, today)]
        return sorted(due, key=lambda p: p.last_contacted or "")
