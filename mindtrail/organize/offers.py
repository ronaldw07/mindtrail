"""Offers side by side. One row per application that has an offer."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mindtrail.organize.db import connect, now_iso
from mindtrail.organize.jobs import clean_date

MONEY_FIELDS = ("base", "bonus", "equity_per_year", "signing")
MAX_MONEY = 10_000_000


@dataclass(frozen=True)
class Offer:
    application_id: str
    base: int
    bonus: int
    equity_per_year: int
    signing: int
    location: str
    start_date: str
    notes: str
    updated_at: str

    @property
    def first_year(self) -> int:
        """Everything you'd be paid in year one: salary, bonus, a year of
        equity vesting, and the signing bonus."""
        return self.base + self.bonus + self.equity_per_year + self.signing


def _money(value) -> int:
    try:
        n = int(float(str(value or 0).replace(",", "").replace("$", "")))
    except ValueError as exc:
        raise ValueError("amounts must be numbers") from exc
    if not 0 <= n <= MAX_MONEY:
        raise ValueError("amounts must be between 0 and 10,000,000")
    return n


def _to_offer(row) -> Offer:
    return Offer(**{k: row[k] for k in row.keys()})


class OfferStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def get(self, application_id: str) -> Offer | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM offers WHERE application_id = ?", (application_id,)).fetchone()
        return _to_offer(row) if row else None

    def all(self) -> list[Offer]:
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM offers").fetchall()
        return sorted((_to_offer(r) for r in rows), key=lambda o: -o.first_year)

    def save(self, application_id: str, fields: dict) -> Offer:
        """Create the offer or change the fields given."""
        current = self.get(application_id)
        values = asdict(current) if current else {
            "application_id": application_id, "base": 0, "bonus": 0, "equity_per_year": 0,
            "signing": 0, "location": "", "start_date": "", "notes": "", "updated_at": ""}
        for key in MONEY_FIELDS:
            if key in fields:
                values[key] = _money(fields[key])
        if "location" in fields:
            values["location"] = str(fields["location"] or "").strip()[:120]
        if "start_date" in fields:
            values["start_date"] = clean_date(fields["start_date"])
        if "notes" in fields:
            values["notes"] = str(fields["notes"] or "")[:4000]
        values["updated_at"] = now_iso()
        try:
            with connect(self._path) as conn:
                conn.execute(
                    "INSERT INTO offers (application_id, base, bonus, equity_per_year, signing, location, "
                    "start_date, notes, updated_at) VALUES (:application_id, :base, :bonus, :equity_per_year, "
                    ":signing, :location, :start_date, :notes, :updated_at) "
                    "ON CONFLICT(application_id) DO UPDATE SET base=:base, bonus=:bonus, "
                    "equity_per_year=:equity_per_year, signing=:signing, location=:location, "
                    "start_date=:start_date, notes=:notes, updated_at=:updated_at", values)
        except Exception as exc:  # sqlite3.IntegrityError: no such application
            raise ValueError(f"no such application: {application_id}") from exc
        return self.get(application_id)

    def delete(self, application_id: str) -> None:
        with connect(self._path) as conn:
            conn.execute("DELETE FROM offers WHERE application_id = ?", (application_id,))
