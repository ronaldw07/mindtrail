"""Named JSON values in the app_state table (see organize/db.py)."""

from __future__ import annotations

import json

from mindtrail.organize.db import connect, now_iso


class AppState:
    def __init__(self, path: str | None = None):
        self._path = path

    def get(self, key: str, default=None):
        with connect(self._path) as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set(self, key: str, value) -> None:
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, json.dumps(value), now_iso()),
            )
