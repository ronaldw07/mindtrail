"""Life areas: Career, School, Health, Social, Money - or whatever you rename
them to. Projects, tasks, and habits carry an area_id."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import connect
from mindtrail.organize.projects import ProjectStore

# Muted hues that read on the dark surfaces and stay distinguishable from
# each other; checked against --surface-raised for a visible dot.
DEFAULT_AREAS = (
    ("Career", "#6d8cff"),
    ("School", "#c8a44a"),
    ("Health", "#3fb27f"),
    ("Social", "#e07a9a"),
    ("Money", "#9b7fe0"),
)
SEEDED_KEY = "areas_seeded"
AREA_TABLES = ("projects", "tasks", "habits")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Area:
    id: str
    name: str
    color: str
    sort: int


def _to_area(row) -> Area:
    return Area(id=row["id"], name=row["name"], color=row["color"], sort=row["sort"])


def _clean(name: str, color: str) -> tuple[str, str]:
    name = name.strip()
    if not name:
        raise ValueError("area name must not be empty")
    if not _HEX.match(color):
        raise ValueError("color must look like #a1b2c3")
    return name[:40], color.lower()


class AreaStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def ensure_seeded(self) -> None:
        """Create the default areas once, ever - not again after you've
        deleted or renamed them."""
        state = AppState(self._path)
        if state.get(SEEDED_KEY):
            return
        if not self.all():
            for i, (name, color) in enumerate(DEFAULT_AREAS):
                self.create(name, color, sort=i)
        state.set(SEEDED_KEY, True)

    def all(self) -> list[Area]:
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM areas ORDER BY sort, name").fetchall()
        return [_to_area(r) for r in rows]

    def get(self, area_id: str) -> Area | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM areas WHERE id = ?", (area_id,)).fetchone()
        return _to_area(row) if row else None

    def create(self, name: str, color: str, sort: int | None = None) -> Area:
        name, color = _clean(name, color)
        with connect(self._path) as conn:
            if sort is None:
                sort = conn.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM areas").fetchone()[0]
            area = Area(id=str(uuid.uuid4()), name=name, color=color, sort=sort)
            conn.execute("INSERT INTO areas (id, name, color, sort) VALUES (?, ?, ?, ?)",
                         (area.id, area.name, area.color, area.sort))
        return area

    def update(self, area_id: str, name: str, color: str) -> Area:
        name, color = _clean(name, color)
        with connect(self._path) as conn:
            cursor = conn.execute("UPDATE areas SET name = ?, color = ? WHERE id = ?",
                                  (name, color, area_id))
            if cursor.rowcount == 0:
                raise ValueError(f"no such area: {area_id}")
        return self.get(area_id)

    def delete(self, area_id: str) -> None:
        """Remove the area and untag everything that used it."""
        with connect(self._path) as conn:
            cursor = conn.execute("DELETE FROM areas WHERE id = ?", (area_id,))
            if cursor.rowcount == 0:
                raise ValueError(f"no such area: {area_id}")
            existing = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            for table in AREA_TABLES:
                if table in existing:
                    conn.execute(f"UPDATE {table} SET area_id = '' WHERE area_id = ?", (area_id,))

    def set_project_area(self, project_id: str, area_id: str) -> None:
        if area_id and self.get(area_id) is None:
            raise ValueError(f"no such area: {area_id}")
        ProjectStore(self._path).set_area(project_id, area_id)

    def project_areas(self) -> dict[str, str]:
        """project id -> area id, for projects that have one."""
        with connect(self._path) as conn:
            rows = conn.execute("SELECT id, area_id FROM projects WHERE area_id != ''").fetchall()
        return {r["id"]: r["area_id"] for r in rows}
