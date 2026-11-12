"""The journey assistant's saved chats: several per journey, each with its
own history, so one conversation about a fitness plan doesn't bleed into
another about internships."""

from __future__ import annotations

import json
import uuid

from mindtrail.organize.db import connect, now_iso

TITLE_CHARS = 60
RESOLUTIONS = ("accepted", "rejected")


def _title_from(message: str) -> str:
    text = " ".join(message.split())
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"


def _row_json(row, with_messages: bool) -> dict:
    out = {"id": row["id"], "project_id": row["project_id"], "title": row["title"] or "New chat",
           "created_at": row["created_at"], "updated_at": row["updated_at"]}
    if with_messages:
        out["messages"] = json.loads(row["messages"] or "[]")
    return out


class JourneyChatStore:
    """table is journey_chats (one journey each) or home_chats (the
    Journeys page, where project_id is always "home")."""

    def __init__(self, path: str | None = None, table: str = "journey_chats"):
        if table not in ("journey_chats", "home_chats"):
            raise ValueError("unknown chat table")
        self._path = path
        self._table = table

    def list(self, project_id: str) -> list[dict]:
        with connect(self._path) as conn:
            rows = conn.execute(
                f"SELECT * FROM {self._table} WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        return [_row_json(r, False) for r in rows]

    def create(self, project_id: str) -> dict:
        now = now_iso()
        chat_id = str(uuid.uuid4())
        with connect(self._path) as conn:
            conn.execute(
                f"INSERT INTO {self._table} (id, project_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (chat_id, project_id, now, now),
            )
        return self.get(chat_id)

    def get(self, chat_id: str) -> dict | None:
        with connect(self._path) as conn:
            row = conn.execute(f"SELECT * FROM {self._table} WHERE id = ?", (chat_id,)).fetchone()
        return _row_json(row, True) if row else None

    def _save(self, chat_id: str, messages: list[dict], title: str) -> None:
        with connect(self._path) as conn:
            conn.execute(
                f"UPDATE {self._table} SET messages = ?, title = ?, updated_at = ? WHERE id = ?",
                (json.dumps(messages), title, now_iso(), chat_id),
            )

    def append_turn(self, chat_id: str, user: str, reply: str, actions: list[dict],
                    title: str = "", ask: dict | None = None) -> dict:
        """Add a question and its answer; the first question names the chat
        unless a title is given (e.g. "Plan: Long run" from a Plan button)."""
        chat = self.get(chat_id)
        if chat is None:
            raise ValueError("no such chat")
        messages = chat["messages"] + [
            {"role": "user", "content": user},
            {"role": "assistant", "content": reply, "actions": actions, **({"ask": ask} if ask else {})},
        ]
        title = chat["title"] if chat["messages"] else _title_from(title or user)
        self._save(chat_id, messages, title)
        return self.get(chat_id)

    def update_action(self, chat_id: str, message: int, action: int,
                      resolved: str = "", fields: dict | None = None) -> dict:
        """Mark a proposal accepted/rejected, or save an edit to it."""
        chat = self.get(chat_id)
        if chat is None:
            raise ValueError("no such chat")
        msgs = chat["messages"]
        if not (0 <= message < len(msgs)) or not (0 <= action < len(msgs[message].get("actions") or [])):
            raise ValueError("no such proposal")
        if resolved and resolved not in RESOLUTIONS:
            raise ValueError("resolved must be accepted or rejected")
        old = msgs[message]["actions"][action]
        new = {**old, **(fields or {}), **({"resolved": resolved} if resolved else {})}
        actions = [new if i == action else a for i, a in enumerate(msgs[message]["actions"])]
        messages = [{**m, "actions": actions} if i == message else m for i, m in enumerate(msgs)]
        self._save(chat_id, messages, chat["title"])
        return self.get(chat_id)

    def delete(self, chat_id: str) -> None:
        with connect(self._path) as conn:
            conn.execute(f"DELETE FROM {self._table} WHERE id = ?", (chat_id,))
