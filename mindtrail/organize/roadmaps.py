"""Roadmaps: a goal broken into draggable, editable steps.

A roadmap belongs to a project. Nodes carry their own canvas position and
a status the user controls (proposed/accepted/rejected/done) plus a note
field that is theirs alone - regeneration only ever adds or updates
proposed nodes, never touching accepted ones or notes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from mindtrail.organize.db import connect, now_iso
from mindtrail.organize.terms import clean_term

STATUSES = ("proposed", "accepted", "rejected", "done")
SHARED_KIND = "shared"
"""A roadmap whose steps show on every other track in the project (the
journey's Year 1, say) - see organize/journey.py."""


@dataclass(frozen=True)
class Roadmap:
    id: str
    project_id: str | None
    goal: str
    created_at: str
    name: str = ""
    """Tab label when a project has several roadmaps; '' shows the goal."""
    kind: str = ""
    """'' for a normal roadmap, SHARED_KIND for a journey's shared steps."""


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
    linked_entries: tuple[str, ...] = ()
    """Memory entry ids linked to this step. Entries live in Chroma, not
    this database, so an id here can never be a real foreign key - it can
    dangle if the entry was since deleted. Comma-joined in storage,
    exactly like depends_on; dangling ids are dropped on the read path in
    web/api.py, not here, since only the caller has a MemoryStore to
    check against."""
    repeat_days: int = 0
    """0 means the step does not repeat. A positive value is a day
    interval (1/7/14/30 for daily/weekly/fortnightly/monthly) - see
    RoadmapNodeStore.set_status for what happens when a repeating step is
    marked done."""
    term: str = ""
    """School term like '2026-fall' (organize/terms.py), or '' for none."""


def _to_roadmap(row) -> Roadmap:
    keys = row.keys()
    return Roadmap(
        id=row["id"],
        project_id=row["project_id"],
        goal=row["goal"],
        created_at=row["created_at"],
        name=row["name"] if "name" in keys else "",
        kind=row["kind"] if "kind" in keys else "",
    )


def _to_node(row) -> RoadmapNode:
    raw = row["depends_on"] or ""
    keys = row.keys()
    raw_linked = row["linked_entries"] if "linked_entries" in keys else ""
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
        due_date=row["due_date"] if "due_date" in keys else "",
        linked_entries=tuple(e for e in (raw_linked or "").split(",") if e),
        repeat_days=row["repeat_days"] if "repeat_days" in keys else 0,
        term=row["term"] if "term" in keys else "",
    )


class RoadmapStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def create(
        self, goal: str, project_id: str | None = None, name: str = "", kind: str = ""
    ) -> Roadmap:
        clean = goal.strip()
        if not clean:
            raise ValueError("goal must not be empty")
        roadmap = Roadmap(
            id=str(uuid.uuid4()), project_id=project_id, goal=clean,
            created_at=now_iso(), name=name.strip()[:60], kind=kind,
        )
        return self.restore(roadmap)

    def restore(self, roadmap: Roadmap) -> Roadmap:
        """Re-insert a roadmap exactly as it was, id included - same
        reasoning as RoadmapNodeStore.restore below: `mindtrail import`
        must recognize its own previous run by id, not duplicate under a
        fresh one.
        """
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO roadmaps (id, project_id, goal, created_at, name, kind) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (roadmap.id, roadmap.project_id, roadmap.goal, roadmap.created_at,
                 roadmap.name, roadmap.kind),
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

    def list_for_project(self, project_id: str) -> list[Roadmap]:
        """Every roadmap (track) in a project, oldest first."""
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM roadmaps WHERE project_id = ? ORDER BY created_at, rowid",
                (project_id,),
            ).fetchall()
        return [_to_roadmap(r) for r in rows]

    def rename(self, roadmap_id: str, name: str | None = None, goal: str | None = None) -> Roadmap:
        current = self.get(roadmap_id)
        if current is None:
            raise ValueError(f"no such roadmap: {roadmap_id}")
        new_name = current.name if name is None else name.strip()[:60]
        new_goal = current.goal if goal is None else goal.strip()
        if not new_goal:
            raise ValueError("goal must not be empty")
        with connect(self._path) as conn:
            conn.execute("UPDATE roadmaps SET name = ?, goal = ? WHERE id = ?",
                         (new_name, new_goal, roadmap_id))
        return self.get(roadmap_id)

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
        linked_entries: list[str] | None = None,
        repeat_days: int = 0,
        term: str = "",
    ) -> RoadmapNode:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        node = RoadmapNode(
            id=str(uuid.uuid4()), roadmap_id=roadmap_id, title=title.strip(),
            detail=detail.strip(), status=status, note="", x=x, y=y,
            depends_on=tuple(depends_on or []), created_at=now_iso(),
            due_date=due_date.strip(),
            linked_entries=tuple(linked_entries or []),
            repeat_days=repeat_days,
            term=clean_term(term),
        )
        return self.restore(node)

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
                "depends_on, created_at, due_date, linked_entries, repeat_days, term) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    node.id, node.roadmap_id, node.title, node.detail,
                    node.status, node.note, node.x, node.y,
                    ",".join(node.depends_on), node.created_at, node.due_date,
                    ",".join(node.linked_entries), node.repeat_days, node.term,
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
        if status == "done":
            node = self.get(node_id)
            if node is not None and node.repeat_days > 0:
                # A repeating step never actually rests at 'done' - it
                # resets to 'accepted' with its due date pushed forward,
                # so the one card keeps coming back instead of the canvas
                # filling up with a clone every week. This is the single
                # choke point every status change goes through (API and
                # any future CLI command alike), so neither can bypass it.
                #
                # The new due date is anchored on *today*, not on the old
                # due date - completing an overdue step should not
                # immediately recreate an overdue step. Anchoring on the
                # stale due date is the tempting "fix" here; don't.
                today = datetime.now(timezone.utc).date()
                next_due = (today + timedelta(days=node.repeat_days)).isoformat()
                with connect(self._path) as conn:
                    conn.execute(
                        "UPDATE roadmap_nodes SET status = ?, due_date = ? "
                        "WHERE id = ?",
                        ("accepted", next_due, node_id),
                    )
                return
        self._update(node_id, "status", status)

    def set_note(self, node_id: str, note: str) -> None:
        self._update(node_id, "note", note)

    def set_due_date(self, node_id: str, due_date: str) -> None:
        self._update(node_id, "due_date", due_date.strip())

    def set_term(self, node_id: str, term: str) -> None:
        self._update(node_id, "term", clean_term(term))

    def set_repeat_days(self, node_id: str, repeat_days: int) -> None:
        if repeat_days < 0:
            raise ValueError("repeat_days must not be negative")
        self._update(node_id, "repeat_days", repeat_days)

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

    def set_linked_entries(self, node_id: str, entry_ids: list[str]) -> None:
        self._update(node_id, "linked_entries", ",".join(entry_ids))

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


def duplicate_roadmap(
    roadmaps: RoadmapStore,
    nodes: RoadmapNodeStore,
    source_id: str,
    name: str,
    project_id: str | None = None,
) -> Roadmap:
    """A copy of a roadmap and every step in it - statuses, notes, terms
    and links between steps included - under fresh ids. Lands in the
    source's own project unless `project_id` says otherwise. The source is
    never touched."""
    source = roadmaps.get(source_id)
    if source is None:
        raise ValueError(f"no such roadmap: {source_id}")
    copy = roadmaps.create(
        source.goal, project_id=project_id or source.project_id,
        name=name or source.name, kind="",
    )
    old_steps = nodes.for_roadmap(source_id)
    new_ids = {n.id: str(uuid.uuid4()) for n in old_steps}
    for n in old_steps:
        nodes.restore(replace(
            n, id=new_ids[n.id], roadmap_id=copy.id,
            depends_on=tuple(new_ids[d] for d in n.depends_on if d in new_ids),
        ))
    return copy
