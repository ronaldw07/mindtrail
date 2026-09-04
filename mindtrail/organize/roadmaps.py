"""Roadmaps: a goal broken into draggable, editable steps.

A roadmap belongs to a project. Nodes carry their own canvas position and
a status the user controls (proposed/accepted/rejected/done) plus a note
field that is theirs alone - regeneration only ever adds or updates
proposed nodes, never touching accepted ones or notes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from mindtrail.organize.db import connect, now_iso

STATUSES = ("proposed", "accepted", "rejected", "done")


@dataclass(frozen=True)
class Roadmap:
    id: str
    project_id: str | None
    goal: str
    created_at: str


@dataclass(frozen=True)
class RoadmapNode:
    id: str
    roadmap_id: str
    title: str
    detail: str
    status: str
    note: str
    x: float
    y: float
    depends_on: tuple[str, ...]
    created_at: str
    due_date: str = ""
    """ISO date (YYYY-MM-DD), or empty for no due date."""


def _to_roadmap(row) -> Roadmap:
    return Roadmap(
        id=row["id"],
        project_id=row["project_id"],
        goal=row["goal"],
        created_at=row["created_at"],
    )


def _to_node(row) -> RoadmapNode:
    raw = row["depends_on"] or ""
    return RoadmapNode(
        id=row["id"],
        roadmap_id=row["roadmap_id"],
        title=row["title"],
        detail=row["detail"],
        status=row["status"],
        note=row["note"],
        x=row["x"],
        y=row["y"],
        depends_on=tuple(d for d in raw.split(",") if d),
        created_at=row["created_at"],
        due_date=row["due_date"] if "due_date" in row.keys() else "",
    )


class RoadmapStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def create(self, goal: str, project_id: str | None = None) -> Roadmap:
        clean = goal.strip()
        if not clean:
            raise ValueError("goal must not be empty")
        roadmap = Roadmap(
            id=str(uuid.uuid4()), project_id=project_id, goal=clean,
            created_at=now_iso(),
        )
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO roadmaps (id, project_id, goal, created_at) "
                "VALUES (?, ?, ?, ?)",
                (roadmap.id, roadmap.project_id, roadmap.goal, roadmap.created_at),
            )
        return roadmap

    def get(self, roadmap_id: str) -> Roadmap | None:
        with connect(self._path) as conn:
            row = conn.execute(
                "SELECT * FROM roadmaps WHERE id = ?", (roadmap_id,)
            ).fetchone()
        return _to_roadmap(row) if row else None

    def for_project(self, project_id: str) -> Roadmap | None:
        """A project has at most one roadmap; the most recent wins if
        more than one somehow exists."""
        with connect(self._path) as conn:
            row = conn.execute(
                "SELECT * FROM roadmaps WHERE project_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        return _to_roadmap(row) if row else None

    def delete(self, roadmap_id: str) -> None:
        with connect(self._path) as conn:
            cursor = conn.execute("DELETE FROM roadmaps WHERE id = ?", (roadmap_id,))
            if cursor.rowcount == 0:
                raise ValueError(f"no such roadmap: {roadmap_id}")


class RoadmapNodeStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def add(
        self,
        roadmap_id: str,
        title: str,
        detail: str = "",
        status: str = "proposed",
        x: float = 0,
        y: float = 0,
        depends_on: list[str] | None = None,
        due_date: str = "",
    ) -> RoadmapNode:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        node = RoadmapNode(
            id=str(uuid.uuid4()), roadmap_id=roadmap_id, title=title.strip(),
            detail=detail.strip(), status=status, note="", x=x, y=y,
            depends_on=tuple(depends_on or []), created_at=now_iso(),
            due_date=due_date.strip(),
        )
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO roadmap_nodes "
                "(id, roadmap_id, title, detail, status, note, x, y, "
                "depends_on, created_at, due_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    node.id, node.roadmap_id, node.title, node.detail,
                    node.status, node.note, node.x, node.y,
                    ",".join(node.depends_on), node.created_at, node.due_date,
                ),
            )
        return node

    def restore(self, node: RoadmapNode) -> RoadmapNode:
        """Re-insert a node exactly as it was, id included.

        `delete` leaves other nodes' `depends_on` pointing at this id
        rather than rewriting them (see `delete` below), so a restore
        under a fresh id would leave those edges dangling forever - the
        id has to come back, not just the content.
        """
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO roadmap_nodes "
                "(id, roadmap_id, title, detail, status, note, x, y, "
                "depends_on, created_at, due_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    node.id, node.roadmap_id, node.title, node.detail,
                    node.status, node.note, node.x, node.y,
                    ",".join(node.depends_on), node.created_at, node.due_date,
                ),
            )
        return node

    def _update(self, node_id: str, column: str, value) -> None:
        with connect(self._path) as conn:
            cursor = conn.execute(
                f"UPDATE roadmap_nodes SET {column} = ? WHERE id = ?",
                (value, node_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"no such node: {node_id}")

    def set_status(self, node_id: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        self._update(node_id, "status", status)

    def set_note(self, node_id: str, note: str) -> None:
        self._update(node_id, "note", note)

    def set_due_date(self, node_id: str, due_date: str) -> None:
        self._update(node_id, "due_date", due_date.strip())

    def move(self, node_id: str, x: float, y: float) -> None:
        with connect(self._path) as conn:
            cursor = conn.execute(
                "UPDATE roadmap_nodes SET x = ?, y = ? WHERE id = ?",
                (x, y, node_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"no such node: {node_id}")

    def set_depends_on(self, node_id: str, depends_on: list[str]) -> None:
        self._update(node_id, "depends_on", ",".join(depends_on))

    def rename(self, node_id: str, title: str, detail: str = "") -> None:
        clean = title.strip()
        if not clean:
            raise ValueError("node title must not be empty")
        with connect(self._path) as conn:
            cursor = conn.execute(
                "UPDATE roadmap_nodes SET title = ?, detail = ? WHERE id = ?",
                (clean, detail.strip(), node_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"no such node: {node_id}")

    def delete(self, node_id: str) -> None:
        with connect(self._path) as conn:
            # Nodes that depended on this one keep a dangling reference
            # rather than being rewritten; the canvas simply will not draw
            # an edge to a ghost, which is a defensible cheap answer.
            cursor = conn.execute(
                "DELETE FROM roadmap_nodes WHERE id = ?", (node_id,)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"no such node: {node_id}")

    def get(self, node_id: str) -> RoadmapNode | None:
        with connect(self._path) as conn:
            row = conn.execute(
                "SELECT * FROM roadmap_nodes WHERE id = ?", (node_id,)
            ).fetchone()
        return _to_node(row) if row else None

    def for_roadmap(self, roadmap_id: str) -> list[RoadmapNode]:
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM roadmap_nodes WHERE roadmap_id = ? "
                "ORDER BY created_at",
                (roadmap_id,),
            ).fetchall()
        return [_to_node(r) for r in rows]
