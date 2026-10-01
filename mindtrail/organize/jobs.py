"""Job applications: the pipeline the Jobs view and the email scan share."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from mindtrail.organize.db import connect, now_iso

PIPELINE = ("saved", "applied", "oa", "interview", "offer")
CLOSED = ("rejected", "withdrawn")
STAGES = PIPELINE + CLOSED
SOURCES = ("manual", "link", "sheet", "email")

EDITABLE_TEXT = ("company", "role", "url", "location", "notes")
EDITABLE_DATES = ("applied_at", "deadline")


@dataclass(frozen=True)
class Application:
    id: str
    company: str
    role: str
    url: str
    location: str
    stage: str
    applied_at: str
    deadline: str
    notes: str
    source: str
    needs_review: bool
    created_at: str
    updated_at: str


def _to_app(row) -> Application:
    return Application(
        id=row["id"], company=row["company"], role=row["role"], url=row["url"],
        location=row["location"], stage=row["stage"], applied_at=row["applied_at"],
        deadline=row["deadline"], notes=row["notes"], source=row["source"],
        needs_review=bool(row["needs_review"]), created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def clean_date(value) -> str:
    """'' for blank, else a valid YYYY-MM-DD or ValueError."""
    text = str(value or "").strip()
    if not text:
        return ""
    date.fromisoformat(text)
    return text


def normalize_company(name: str) -> str:
    """Matching key for a company: case and punctuation-insensitive, with
    common legal suffixes dropped, so "Stripe, Inc." and "stripe" match."""
    words = "".join(c if c.isalnum() else " " for c in name.lower()).split()
    while words and words[-1] in ("inc", "llc", "ltd", "corp", "corporation", "co"):
        words.pop()
    return " ".join(words)


def email_may_move(current: str, new: str) -> bool:
    """Email-driven stage changes only ever move forward.

    A late "thanks for applying" must not undo an interview, and nothing
    an email says reopens an offer, a rejection, or a withdrawal. A
    rejection can land from any open stage. Manual edits skip this.
    """
    if new not in STAGES or current in CLOSED or current == "offer":
        return False
    if new in CLOSED:
        return new == "rejected"
    return PIPELINE.index(new) > PIPELINE.index(current)


class JobStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def create(
        self,
        company: str,
        role: str = "",
        url: str = "",
        location: str = "",
        stage: str = "applied",
        applied_at: str = "",
        deadline: str = "",
        notes: str = "",
        source: str = "manual",
        needs_review: bool = False,
    ) -> Application:
        company = company.strip()
        if not company:
            raise ValueError("company must not be empty")
        if stage not in STAGES:
            raise ValueError(f"unknown stage: {stage}")
        if source not in SOURCES:
            raise ValueError(f"unknown source: {source}")
        stamp = now_iso()
        app = Application(
            id=str(uuid.uuid4()), company=company, role=role.strip(), url=url.strip(),
            location=location.strip(), stage=stage, applied_at=clean_date(applied_at),
            deadline=clean_date(deadline), notes=notes.strip(), source=source,
            needs_review=needs_review, created_at=stamp, updated_at=stamp,
        )
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO applications (id, company, role, url, location, stage, "
                "applied_at, deadline, notes, source, needs_review, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (app.id, app.company, app.role, app.url, app.location, app.stage,
                 app.applied_at, app.deadline, app.notes, app.source,
                 int(app.needs_review), app.created_at, app.updated_at),
            )
        return app

    def get(self, app_id: str) -> Application | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        return _to_app(row) if row else None

    def all(self) -> list[Application]:
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM applications ORDER BY updated_at DESC"
            ).fetchall()
        return [_to_app(r) for r in rows]

    def find(self, company: str, role: str = "") -> Application | None:
        """Same company (normalized) and, if given, same role
        (case-insensitive). Used to dedupe imports and match emails."""
        key = normalize_company(company)
        wanted_role = role.strip().lower()
        for app in self.all():
            if normalize_company(app.company) != key:
                continue
            if not wanted_role or app.role.strip().lower() == wanted_role:
                return app
        return None

    def update(self, app_id: str, fields: dict) -> Application:
        """Manual edit. Unknown keys are ignored; bad values raise."""
        current = self.get(app_id)
        if current is None:
            raise ValueError(f"no such application: {app_id}")
        changes: dict = {}
        for key in EDITABLE_TEXT:
            if key in fields:
                changes[key] = str(fields[key] or "").strip()
        if "company" in changes and not changes["company"]:
            raise ValueError("company must not be empty")
        for key in EDITABLE_DATES:
            if key in fields:
                changes[key] = clean_date(fields[key])
        if "stage" in fields:
            if fields["stage"] not in STAGES:
                raise ValueError(f"unknown stage: {fields['stage']}")
            changes["stage"] = fields["stage"]
        if "needs_review" in fields:
            changes["needs_review"] = int(bool(fields["needs_review"]))
        if not changes:
            return current
        changes["updated_at"] = now_iso()
        assignments = ", ".join(f"{k} = ?" for k in changes)
        with connect(self._path) as conn:
            conn.execute(
                f"UPDATE applications SET {assignments} WHERE id = ?",
                (*changes.values(), app_id),
            )
        return self.get(app_id)

    def advance_from_email(self, app_id: str, stage: str) -> bool:
        """Apply an email-derived stage if email_may_move allows it."""
        current = self.get(app_id)
        if current is None or not email_may_move(current.stage, stage):
            return False
        self.update(app_id, {"stage": stage})
        return True

    def delete(self, app_id: str) -> None:
        with connect(self._path) as conn:
            cursor = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
            if cursor.rowcount == 0:
                raise ValueError(f"no such application: {app_id}")
