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
    instructions: str = ""
    advice: str = ""
    advice_generated_at: str = ""
    advice_basis_count: int = 0
    """How many entries the stored advice was generated from. Compared
    against the project's current entry count to detect staleness."""


def _to_project(row) -> Project:
    keys = row.keys()
    return Project(
        id=row["id"],
        name=row["name"],
        created_at=row["created_at"],
        instructions=row["instructions"] if "instructions" in keys else "",
        advice=row["advice"] if "advice" in keys else "",
        advice_generated_at=(
            row["advice_generated_at"] if "advice_generated_at" in keys else ""
        ),
        advice_basis_count=(
            row["advice_basis_count"] if "advice_basis_count" in keys else 0
        ),
    )


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

    def set_instructions(self, project_id: str, instructions: str) -> None:
        """Guidance injected into every research prompt in this project."""
        with connect(self._path) as conn:
            cursor = conn.execute(
                "UPDATE projects SET instructions = ? WHERE id = ?",
                (instructions.strip(), project_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"no such project: {project_id}")

    def save_advice(self, project_id: str, advice: str, basis_count: int) -> None:
        """Store generated advice along with what it was based on.

        basis_count is how many entries existed at generation time, so a
        later view can tell whether the advice has fallen behind.
        """
        with connect(self._path) as conn:
            cursor = conn.execute(
                "UPDATE projects SET advice = ?, advice_generated_at = ?, "
                "advice_basis_count = ? WHERE id = ?",
                (advice, now_iso(), basis_count, project_id),
            )
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
