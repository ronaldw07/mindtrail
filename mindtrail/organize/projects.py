"""Projects: manually created containers for conversations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from mindtrail.organize.db import connect, now_iso


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    created_at: str


def _to_project(row) -> Project:
    return Project(id=row["id"], name=row["name"], created_at=row["created_at"])


class ProjectStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def create(self, name: str) -> Project:
        clean = name.strip()
        if not clean:
            raise ValueError("project name must not be empty")

        project = Project(id=str(uuid.uuid4()), name=clean, created_at=now_iso())
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
                (project.id, project.name, project.created_at),
            )
        return project

    def rename(self, project_id: str, name: str) -> None:
        clean = name.strip()
        if not clean:
            raise ValueError("project name must not be empty")

        with connect(self._path) as conn:
            cursor = conn.execute(
                "UPDATE projects SET name = ? WHERE id = ?", (clean, project_id)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"no such project: {project_id}")

    def delete(self, project_id: str) -> None:
        """Delete the project. Its conversations are unfiled, not deleted.

        Losing research because a folder was removed is the wrong
        default; ON DELETE SET NULL in the schema does the unfiling.
        """
        with connect(self._path) as conn:
            cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            if cursor.rowcount == 0:
                raise ValueError(f"no such project: {project_id}")

    def get(self, project_id: str) -> Project | None:
        with connect(self._path) as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return _to_project(row) if row else None

    def all(self) -> list[Project]:
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY LOWER(name)"
            ).fetchall()
        return [_to_project(r) for r in rows]
