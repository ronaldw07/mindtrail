"""Conversations: renameable, movable, pinnable threads of entries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from mindtrail.organize.db import connect, now_iso

TITLE_MAX_CHARS = 60


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    project_id: str | None
    pinned: bool
    unread: bool
    created_at: str
    updated_at: str


def _to_conversation(row) -> Conversation:
    return Conversation(
        id=row["id"],
        title=row["title"],
        project_id=row["project_id"],
        pinned=bool(row["pinned"]),
        unread=bool(row["unread"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def title_from_question(question: str) -> str:
    """First line of the question, trimmed to a sidebar-sized label."""
    first = question.strip().splitlines()[0] if question.strip() else "New chat"
    return first[:TITLE_MAX_CHARS] or "New chat"


class ConversationStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def create(self, title: str, project_id: str | None = None) -> Conversation:
        stamp = now_iso()
        conversation = Conversation(
            id=str(uuid.uuid4()),
            title=title.strip() or "New chat",
            project_id=project_id,
            pinned=False,
            unread=False,
            created_at=stamp,
            updated_at=stamp,
        )
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO conversations "
                "(id, title, project_id, pinned, unread, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation.id,
                    conversation.title,
                    conversation.project_id,
                    int(conversation.pinned),
                    int(conversation.unread),
                    conversation.created_at,
                    conversation.updated_at,
                ),
            )
        return conversation

    def _update(self, conversation_id: str, column: str, value) -> None:
        """Single-column update. `column` is never user-supplied - callers
        pass a literal - so it is safe to interpolate where a bound
        parameter is not allowed."""
        with connect(self._path) as conn:
            cursor = conn.execute(
                f"UPDATE conversations SET {column} = ?, updated_at = ? WHERE id = ?",
                (value, now_iso(), conversation_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"no such conversation: {conversation_id}")

    def rename(self, conversation_id: str, title: str) -> None:
        clean = title.strip()
        if not clean:
            raise ValueError("conversation title must not be empty")
        self._update(conversation_id, "title", clean[:TITLE_MAX_CHARS])

    def move(self, conversation_id: str, project_id: str | None) -> None:
        """Move into a project, or pass None to unfile it."""
        self._update(conversation_id, "project_id", project_id)

    def set_pinned(self, conversation_id: str, pinned: bool) -> None:
        self._update(conversation_id, "pinned", int(pinned))

    def set_unread(self, conversation_id: str, unread: bool) -> None:
        self._update(conversation_id, "unread", int(unread))

    def touch(self, conversation_id: str) -> None:
        """Mark activity without changing anything else."""
        self._update(conversation_id, "updated_at", now_iso())

    def delete(self, conversation_id: str) -> None:
        """Remove the conversation record.

        Callers are responsible for deleting the entries that belong to
        it; this table does not know about Chroma.
        """
        with connect(self._path) as conn:
            cursor = conn.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"no such conversation: {conversation_id}")

    def get(self, conversation_id: str) -> Conversation | None:
        with connect(self._path) as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return _to_conversation(row) if row else None

    def all(self) -> list[Conversation]:
        """Pinned first, then most recently active."""
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY pinned DESC, updated_at DESC"
            ).fetchall()
        return [_to_conversation(r) for r in rows]

    def in_project(self, project_id: str | None) -> list[Conversation]:
        with connect(self._path) as conn:
            if project_id is None:
                rows = conn.execute(
                    "SELECT * FROM conversations WHERE project_id IS NULL "
                    "ORDER BY pinned DESC, updated_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM conversations WHERE project_id = ? "
                    "ORDER BY pinned DESC, updated_at DESC",
                    (project_id,),
                ).fetchall()
        return [_to_conversation(r) for r in rows]
