"""Gmail messages the job scan has already classified (gmail_seen table)."""

from __future__ import annotations

from mindtrail.organize.db import connect, now_iso


class EmailLog:
    def __init__(self, path: str | None = None):
        self._path = path

    def has(self, message_id: str) -> bool:
        with connect(self._path) as conn:
            row = conn.execute(
                "SELECT 1 FROM gmail_seen WHERE message_id = ?", (message_id,)
            ).fetchone()
        return row is not None

    def record(self, message_id: str, application_id: str, label: str,
               subject: str, received_at: str) -> None:
        with connect(self._path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO gmail_seen (message_id, application_id, label, "
                "subject, received_at, seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, application_id, label, subject, received_at, now_iso()),
            )

    def for_application(self, application_id: str) -> list[dict]:
        """Subject, date, and label only - bodies are never stored."""
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT subject, received_at, label FROM gmail_seen "
                "WHERE application_id = ? ORDER BY received_at DESC",
                (application_id,),
            ).fetchall()
        return [dict(r) for r in rows]
