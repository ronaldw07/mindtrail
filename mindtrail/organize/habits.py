"""Habits: daily or N-times-a-week check-ins, with streaks.

Streak rules, both "still alive" until the period is actually over:
- daily (target 7): consecutive logged days ending today, or ending
  yesterday if today isn't logged yet - an unchecked morning isn't a
  broken streak.
- N a week (target 1-6): consecutive Monday-start weeks that hit the
  target, counting this week only once it's hit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from mindtrail.organize.db import connect, now_iso

DAILY = 7
BACKFILL_DAYS = 7  # how far back a missed check-in can still be logged


@dataclass(frozen=True)
class Habit:
    id: str
    name: str
    area_id: str
    target_per_week: int
    archived: bool
    sort: int
    created_at: str


def _to_habit(row) -> Habit:
    return Habit(id=row["id"], name=row["name"], area_id=row["area_id"],
                 target_per_week=row["target_per_week"], archived=bool(row["archived"]),
                 sort=row["sort"], created_at=row["created_at"])


def _target(value) -> int:
    target = int(value)
    if not 1 <= target <= DAILY:
        raise ValueError("target must be 1 to 7 times a week")
    return target


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def streak(done: set[date], target: int, today: date) -> int:
    if target >= DAILY:
        day = today if today in done else today - timedelta(days=1)
        count = 0
        while day in done:
            count += 1
            day -= timedelta(days=1)
        return count

    def hits(start: date) -> int:
        return sum(1 for i in range(7) if start + timedelta(days=i) in done)

    week = week_start(today)
    if hits(week) < target:
        week -= timedelta(days=7)
    count = 0
    while hits(week) >= target:
        count += 1
        week -= timedelta(days=7)
    return count


def this_week_count(done: set[date], today: date) -> int:
    start = week_start(today)
    return sum(1 for d in done if start <= d <= today)


class HabitStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def create(self, name: str, target_per_week: int = DAILY, area_id: str = "") -> Habit:
        name = name.strip()
        if not name:
            raise ValueError("habit name must not be empty")
        with connect(self._path) as conn:
            sort = conn.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM habits").fetchone()[0]
            habit = Habit(id=str(uuid.uuid4()), name=name[:80], area_id=area_id,
                          target_per_week=_target(target_per_week), archived=False,
                          sort=sort, created_at=now_iso())
            conn.execute(
                "INSERT INTO habits (id, name, area_id, target_per_week, archived, sort, "
                "created_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
                (habit.id, habit.name, habit.area_id, habit.target_per_week, habit.sort,
                 habit.created_at),
            )
        return habit

    def get(self, habit_id: str) -> Habit | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
        return _to_habit(row) if row else None

    def all(self, include_archived: bool = False) -> list[Habit]:
        where = "" if include_archived else "WHERE archived = 0 "
        with connect(self._path) as conn:
            rows = conn.execute(f"SELECT * FROM habits {where}ORDER BY sort").fetchall()
        return [_to_habit(r) for r in rows]

    def update(self, habit_id: str, fields: dict) -> Habit:
        if self.get(habit_id) is None:
            raise ValueError(f"no such habit: {habit_id}")
        changes: dict = {}
        if "name" in fields:
            name = str(fields["name"] or "").strip()
            if not name:
                raise ValueError("habit name must not be empty")
            changes["name"] = name[:80]
        if "target_per_week" in fields:
            changes["target_per_week"] = _target(fields["target_per_week"])
        if "area_id" in fields:
            changes["area_id"] = str(fields["area_id"] or "")
        if "archived" in fields:
            changes["archived"] = int(bool(fields["archived"]))
        if changes:
            assignments = ", ".join(f"{k} = ?" for k in changes)
            with connect(self._path) as conn:
                conn.execute(f"UPDATE habits SET {assignments} WHERE id = ?",
                             (*changes.values(), habit_id))
        return self.get(habit_id)

    def delete(self, habit_id: str) -> None:
        with connect(self._path) as conn:
            cursor = conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
            if cursor.rowcount == 0:
                raise ValueError(f"no such habit: {habit_id}")

    def toggle(self, habit_id: str, day: date, today: date) -> bool:
        """Log or un-log `day`. Returns whether it is now logged. Future
        days and days older than BACKFILL_DAYS can't be changed."""
        if self.get(habit_id) is None:
            raise ValueError(f"no such habit: {habit_id}")
        if day > today or day < today - timedelta(days=BACKFILL_DAYS):
            raise ValueError("only the last week can be checked off")
        with connect(self._path) as conn:
            removed = conn.execute(
                "DELETE FROM habit_logs WHERE habit_id = ? AND date = ?",
                (habit_id, day.isoformat()),
            ).rowcount
            if removed:
                return False
            conn.execute("INSERT INTO habit_logs (habit_id, date) VALUES (?, ?)",
                         (habit_id, day.isoformat()))
        return True

    def logs_since(self, since: date) -> dict[str, set[date]]:
        """habit id -> logged dates on or after `since`."""
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT habit_id, date FROM habit_logs WHERE date >= ?", (since.isoformat(),)
            ).fetchall()
        logs: dict[str, set[date]] = {}
        for r in rows:
            logs.setdefault(r["habit_id"], set()).add(date.fromisoformat(r["date"]))
        return logs
