"""The sub-steps inside one journey step: the concrete, checkable things
that get you from "Apply for summer internships" to done, in order."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import date

from mindtrail.organize.db import connect, now_iso

MAX_TITLE = 120
MAX_DETAIL = 600
MAX_NEEDS = 60


def clean_due(value) -> str:
    """A real YYYY-MM-DD day, or '' for anything else."""
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text).isoformat() if len(text) == 10 else ""
    except ValueError:
        return ""


@dataclass(frozen=True)
class StepTask:
    id: str
    node_id: str
    title: str
    detail: str
    done: bool
    due: str
    position: float
    needs: str = ""
    """What finishing it should produce, e.g. "Vertical jump"; '' if nothing."""
    unit: str = ""
    result: str = ""
    """What they entered for `needs`; required before it can be done."""


def _task(row) -> StepTask:
    keys = row.keys()
    extra = {k: row[k] for k in ("needs", "unit", "result") if k in keys}
    return StepTask(row["id"], row["node_id"], row["title"], row["detail"], bool(row["done"]),
                    row["due"], row["position"], **extra)


def _short(value, limit: int = MAX_NEEDS) -> str:
    return " ".join(str(value or "").split())[:limit]


class StepTaskStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def for_node(self, node_id: str) -> list[StepTask]:
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM step_tasks WHERE node_id = ? ORDER BY position, created_at",
                (node_id,)).fetchall()
        return [_task(r) for r in rows]

    def get(self, task_id: str) -> StepTask | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM step_tasks WHERE id = ?", (task_id,)).fetchone()
        return _task(row) if row else None

    def progress(self) -> dict[str, tuple[int, int]]:
        """node_id -> (done, total), for every step that has sub-steps."""
        with connect(self._path) as conn:
            rows = conn.execute("SELECT node_id, SUM(done) AS done, COUNT(*) AS total "
                                "FROM step_tasks GROUP BY node_id").fetchall()
        return {r["node_id"]: (int(r["done"]), int(r["total"])) for r in rows}

    def add(self, node_id: str, title: str, detail: str = "", due: str = "",
            needs: str = "", unit: str = "") -> StepTask:
        title = " ".join(str(title).split())[:MAX_TITLE]
        if not title:
            raise ValueError("a sub-step needs a title")
        task_id = str(uuid.uuid4())
        with connect(self._path) as conn:
            last = conn.execute("SELECT MAX(position) FROM step_tasks WHERE node_id = ?",
                                (node_id,)).fetchone()[0]
            conn.execute(
                "INSERT INTO step_tasks (id, node_id, title, detail, due, position, created_at, "
                "needs, unit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, node_id, title, str(detail).strip()[:MAX_DETAIL], clean_due(due),
                 (last or 0) + 1, now_iso(), _short(needs), _short(unit, 20)))
        return self.get(task_id)

    def update(self, task_id: str, *, title=None, detail=None, done=None, due=None,
               needs=None, unit=None, result=None) -> StepTask:
        """A sub-step that needs a result can't be done without one."""
        current = self.get(task_id)
        if current is None:
            raise ValueError("that sub-step no longer exists")
        changes = {}
        if needs is not None:
            changes["needs"] = _short(needs)
        if unit is not None:
            changes["unit"] = _short(unit, 20)
        if result is not None:
            changes["result"] = _short(result, 200)
        will_need = changes.get("needs", current.needs)
        will_have = changes.get("result", current.result)
        if done and will_need and not will_have:
            raise ValueError(f"Enter your {will_need.lower()} first")
        if title is not None:
            changes["title"] = " ".join(str(title).split())[:MAX_TITLE]
            if not changes["title"]:
                raise ValueError("a sub-step needs a title")
        if detail is not None:
            changes["detail"] = str(detail).strip()[:MAX_DETAIL]
        if done is not None:
            changes["done"] = 1 if done else 0
        if due is not None:
            changes["due"] = clean_due(due)
        if changes:
            with connect(self._path) as conn:
                conn.execute(f"UPDATE step_tasks SET {', '.join(k + ' = ?' for k in changes)} "
                             "WHERE id = ?", (*changes.values(), task_id))
        return self.get(task_id)

    def all_done(self, node_id: str) -> bool | None:
        """True when every sub-step is done, False when some aren't, None
        when the step has none."""
        tasks = self.for_node(node_id)
        return all(t.done for t in tasks) if tasks else None

    def reorder(self, node_id: str, order: list[str]) -> None:
        """Renumber a step's sub-steps to match order; ids not listed keep
        their place after the listed ones."""
        known = [t.id for t in self.for_node(node_id)]
        ids = [i for i in order if i in known] + [i for i in known if i not in order]
        with connect(self._path) as conn:
            conn.executemany("UPDATE step_tasks SET position = ? WHERE id = ?",
                             [(n + 1, i) for n, i in enumerate(ids)])

    def sort_by_date(self, node_id: str) -> None:
        """Done stops first as they were, then the rest by due day; undated
        ones keep their order at the end."""
        tasks = self.for_node(node_id)
        ordered = ([t for t in tasks if t.done]
                   + sorted((t for t in tasks if not t.done), key=lambda t: t.due or "9999-99-99"))
        self.reorder(node_id, [t.id for t in ordered])

    def clear_unfinished(self, node_id: str) -> int:
        with connect(self._path) as conn:
            return conn.execute("DELETE FROM step_tasks WHERE node_id = ? AND done = 0",
                                (node_id,)).rowcount

    def due_by(self, last_day: str) -> list[dict]:
        """Unfinished sub-steps due on or before last_day, oldest first,
        with the step and journey (project) each belongs to."""
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT t.*, n.title AS step_title, r.project_id FROM step_tasks t "
                "JOIN roadmap_nodes n ON n.id = t.node_id JOIN roadmaps r ON r.id = n.roadmap_id "
                "WHERE t.done = 0 AND t.due != '' AND t.due <= ? ORDER BY t.due, t.position",
                (last_day,)).fetchall()
        return [{**asdict(_task(r)), "step_title": r["step_title"], "project_id": r["project_id"]}
                for r in rows]

    def delete(self, task_id: str) -> None:
        with connect(self._path) as conn:
            conn.execute("DELETE FROM step_tasks WHERE id = ?", (task_id,))
