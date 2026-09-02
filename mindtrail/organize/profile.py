"""The user's own background, available to everything that reasons.

Answers, highlights, and roadmaps are all better when the system knows
who is asking - a resume, a degree, a stage of career. This is stored
once, edited by hand, and can be drafted from documents already
uploaded so it does not start from a blank box.
"""

from __future__ import annotations

from dataclasses import dataclass

from mindtrail.organize.db import connect, now_iso

MAX_PROFILE_CHARS = 4000


@dataclass(frozen=True)
class Profile:
    content: str
    updated_at: str

    @property
    def is_empty(self) -> bool:
        return not self.content.strip()


class ProfileStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def get(self) -> Profile:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        if row is None:
            return Profile(content="", updated_at="")
        return Profile(content=row["content"], updated_at=row["updated_at"])

    def save(self, content: str) -> Profile:
        """Upsert the single row, truncating to keep prompts bounded."""
        trimmed = content.strip()[:MAX_PROFILE_CHARS]
        stamp = now_iso()
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO profile (id, content, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET content = ?, updated_at = ?",
                (trimmed, stamp, trimmed, stamp),
            )
        return Profile(content=trimmed, updated_at=stamp)
