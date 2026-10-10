"""Behavioral interview stories (situation / task / action / result)."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass

from mindtrail.organize.db import connect, now_iso

MAX_FIELD = 4000
TEXT_FIELDS = ("situation", "task", "action", "result", "used_in")


@dataclass(frozen=True)
class Story:
    id: str
    title: str
    situation: str
    task: str
    action: str
    result: str
    themes: str
    used_in: str
    created_at: str
    updated_at: str

    @property
    def theme_list(self) -> list[str]:
        return [t for t in self.themes.split(",") if t]


def clean_themes(value) -> str:
    """Lower-cased, trimmed, de-duplicated, comma-separated."""
    raw = value.split(",") if isinstance(value, str) else list(value or [])
    seen: list[str] = []
    for theme in raw:
        theme = " ".join(str(theme).lower().split())[:30]
        if theme and theme not in seen:
            seen.append(theme)
    return ",".join(seen)


def _to_story(row) -> Story:
    return Story(**{k: row[k] for k in row.keys()})


class StoryStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def create(self, title: str, **fields) -> Story:
        title = title.strip()
        if not title:
            raise ValueError("a story needs a title")
        stamp = now_iso()
        s = Story(id=str(uuid.uuid4()), title=title[:120],
                  **{f: str(fields.get(f, "") or "")[:MAX_FIELD] for f in TEXT_FIELDS},
                  themes=clean_themes(fields.get("themes", "")), created_at=stamp, updated_at=stamp)
        with connect(self._path) as conn:
            conn.execute("INSERT INTO stories (id, title, situation, task, action, result, themes, "
                         "used_in, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (s.id, s.title, s.situation, s.task, s.action, s.result, s.themes,
                          s.used_in, s.created_at, s.updated_at))
        return s

    def get(self, story_id: str) -> Story | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        return _to_story(row) if row else None

    def all(self) -> list[Story]:
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM stories ORDER BY updated_at DESC").fetchall()
        return [_to_story(r) for r in rows]

    def update(self, story_id: str, fields: dict) -> Story:
        if self.get(story_id) is None:
            raise ValueError(f"no such story: {story_id}")
        changes: dict = {}
        if "title" in fields:
            title = str(fields["title"] or "").strip()
            if not title:
                raise ValueError("a story needs a title")
            changes["title"] = title[:120]
        for key in TEXT_FIELDS:
            if key in fields:
                changes[key] = str(fields[key] or "")[:MAX_FIELD]
        if "themes" in fields:
            changes["themes"] = clean_themes(fields["themes"])
        if changes:
            changes["updated_at"] = now_iso()
            with connect(self._path) as conn:
                conn.execute(f"UPDATE stories SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                             (*changes.values(), story_id))
        return self.get(story_id)

    def delete(self, story_id: str) -> None:
        with connect(self._path) as conn:
            if conn.execute("DELETE FROM stories WHERE id = ?", (story_id,)).rowcount == 0:
                raise ValueError(f"no such story: {story_id}")

    def themes(self) -> list[tuple[str, int]]:
        """Every theme with how many stories carry it, most used first."""
        counts: dict[str, int] = {}
        for story in self.all():
            for theme in story.theme_list:
                counts[theme] = counts.get(theme, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
