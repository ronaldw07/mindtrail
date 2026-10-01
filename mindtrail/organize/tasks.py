"""To-dos that aren't roadmap steps: job follow-ups and the general inbox.

One table for both, so Today reads a single task list. A job task has an
application_id; a general one doesn't.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from mindtrail.organize.db import connect, now_iso
from mindtrail.organize.jobs import clean_date


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    due_date: str
    done: bool
    done_at: str
    application_id: str | None
    area_id: str
    source_message_id: str
    created_at: str


def _to_task(row) -> Task:
    return Task(
        id=row["id"], title=row["title"], due_date=row["due_date"],
        done=bool(row["done"]), done_at=row["done_at"],
        application_id=row["application_id"], area_id=row["area_id"],
        source_message_id=row["source_message_id"], created_at=row["created_at"],
    )


class TaskStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def add(
        self,
        title: str,
        due_date: str = "",
        application_id: str | None = None,
        area_id: str = "",
        source_message_id: str = "",
    ) -> Task:
        title = title.strip()
        if not title:
            raise ValueError("task title must not be empty")
        task = Task(
            id=str(uuid.uuid4()), title=title, due_date=clean_date(due_date), done=False,
            done_at="", application_id=application_id or None, area_id=area_id,
            source_message_id=source_message_id, created_at=now_iso(),
        )
        try:
            with connect(self._path) as conn:
                conn.execute(
                    "INSERT INTO tasks (id, title, due_date, done, done_at, application_id, "
                    "area_id, source_message_id, created_at) VALUES (?, ?, ?, 0, '', ?, ?, ?, ?)",
                    (task.id, task.title, task.due_date, task.application_id, task.area_id,
                     task.source_message_id, task.created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"no such application: {application_id}") from exc
        return task

    def get(self, task_id: str) -> Task | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _to_task(row) if row else None

    def _select(self, where: str = "", params: tuple = ()) -> list[Task]:
        # Undated tasks sort after dated ones, oldest-created first.
        sql = (
            "SELECT * FROM tasks "
            + (f"WHERE {where} " if where else "")
            + "ORDER BY due_date = '', due_date, created_at"
        )
        with connect(self._path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_to_task(r) for r in rows]

    def all(self) -> list[Task]:
        return self._select()

    def open(self) -> list[Task]:
        return self._select("done = 0")

    def for_application(self, application_id: str) -> list[Task]:
        return self._select("application_id = ?", (application_id,))

    def done_since(self, iso_timestamp: str) -> list[Task]:
        return self._select("done = 1 AND done_at >= ?", (iso_timestamp,))

    def roll_over(self, today: str, to: str) -> int:
        """Move every open task due today or earlier to `to`. Returns how
        many moved."""
        to = clean_date(to)
        with connect(self._path) as conn:
            return conn.execute(
                "UPDATE tasks SET due_date = ? WHERE done = 0 AND due_date != '' "
                "AND due_date <= ?", (to, clean_date(today)),
            ).rowcount

    def has_source_message(self, message_id: str) -> bool:
        with connect(self._path) as conn:
            row = conn.execute(
                "SELECT 1 FROM tasks WHERE source_message_id = ?", (message_id,)
            ).fetchone()
        return row is not None

    def update(self, task_id: str, fields: dict) -> Task:
        current = self.get(task_id)
        if current is None:
            raise ValueError(f"no such task: {task_id}")
        changes: dict = {}
        if "title" in fields:
            title = str(fields["title"] or "").strip()
            if not title:
                raise ValueError("task title must not be empty")
            changes["title"] = title
        if "due_date" in fields:
            changes["due_date"] = clean_date(fields["due_date"])
        if "area_id" in fields:
            changes["area_id"] = str(fields["area_id"] or "")
        if "done" in fields:
            done = bool(fields["done"])
            changes["done"] = int(done)
            changes["done_at"] = now_iso() if done else ""
        if not changes:
            return current
        assignments = ", ".join(f"{k} = ?" for k in changes)
        with connect(self._path) as conn:
            conn.execute(
                f"UPDATE tasks SET {assignments} WHERE id = ?", (*changes.values(), task_id)
            )
        return self.get(task_id)

    def delete(self, task_id: str) -> None:
        with connect(self._path) as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            if cursor.rowcount == 0:
                raise ValueError(f"no such task: {task_id}")
