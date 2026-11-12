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
    node_id: str = ""
    """The journey step this is a daily goal for, or ''."""
    track_id: str = ""
    """Or the journey path it serves as a whole."""
    journey_id: str = ""
    """Or the whole journey (its project id)."""


def _to_habit(row) -> Habit:
    keys = row.keys()
    return Habit(id=row["id"], name=row["name"], area_id=row["area_id"],
                 target_per_week=row["target_per_week"], archived=bool(row["archived"]),
                 sort=row["sort"], created_at=row["created_at"], node_id=row["node_id"],
                 track_id=row["track_id"] if "track_id" in keys else "",
                 journey_id=row["journey_id"] if "journey_id" in keys else "")


SCOPES = ("node_id", "track_id", "journey_id")


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

    def create(self, name: str, target_per_week: int = DAILY, area_id: str = "",
               node_id: str = "", track_id: str = "", journey_id: str = "") -> Habit:
        name = name.strip()
        if not name:
            raise ValueError("habit name must not be empty")
        with connect(self._path) as conn:
            sort = conn.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM habits").fetchone()[0]
            habit = Habit(id=str(uuid.uuid4()), name=name[:80], area_id=area_id,
                          target_per_week=_target(target_per_week), archived=False,
                          sort=sort, created_at=now_iso(), node_id=node_id, track_id=track_id,
                          journey_id=journey_id)
            conn.execute(
                "INSERT INTO habits (id, name, area_id, target_per_week, archived, sort, "
                "created_at, node_id, track_id, journey_id) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
                (habit.id, habit.name, habit.area_id, habit.target_per_week, habit.sort,
                 habit.created_at, habit.node_id, habit.track_id, habit.journey_id),
            )
        return habit

    def set_scope(self, habit_id: str, scope: str, target: str) -> Habit:
        """Make a daily goal serve one step, path or journey instead."""
        if scope not in SCOPES:
            raise ValueError("unknown scope")
        values = {s: (target if s == scope else "") for s in SCOPES}
        with connect(self._path) as conn:
            conn.execute("UPDATE habits SET node_id = ?, track_id = ?, journey_id = ? WHERE id = ?",
                         (values["node_id"], values["track_id"], values["journey_id"], habit_id))
        return self.get(habit_id)

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

    def for_node(self, node_id: str) -> list[Habit]:
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM habits WHERE node_id = ? AND archived = 0 ORDER BY sort",
                                (node_id,)).fetchall()
        return [_to_habit(r) for r in rows]

    def for_track(self, track_id: str) -> list[Habit]:
        return self._where("track_id", track_id)

    def for_journey(self, journey_id: str) -> list[Habit]:
        return self._where("journey_id", journey_id)

    def _where(self, column: str, value: str) -> list[Habit]:
        if column not in SCOPES or not value:
            return []
        with connect(self._path) as conn:
            rows = conn.execute(f"SELECT * FROM habits WHERE {column} = ? AND archived = 0 ORDER BY sort",
                                (value,)).fetchall()
        return [_to_habit(r) for r in rows]

    def steps(self) -> dict[str, dict]:
        """habit id -> what it serves in a journey, for habits whose step,
        path or journey still exists: {kind: step|path|journey, id (the
        step's, else ''), title, project_id}."""
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT h.id AS habit_id, 'step' AS kind, n.id, n.title, r.project_id FROM habits h "
                "JOIN roadmap_nodes n ON n.id = h.node_id JOIN roadmaps r ON r.id = n.roadmap_id "
                "UNION ALL "
                "SELECT h.id, 'path', '', COALESCE(NULLIF(r.name, ''), r.goal), r.project_id FROM habits h "
                "JOIN roadmaps r ON r.id = h.track_id "
                "UNION ALL "
                "SELECT h.id, 'journey', '', p.name, p.id FROM habits h "
                "JOIN projects p ON p.id = h.journey_id").fetchall()
        return {r["habit_id"]: {"kind": r["kind"], "id": r["id"], "title": r["title"],
                                "project_id": r["project_id"]} for r in rows}

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
