"""Short-lived hold for deleted conversations and roadmap nodes, so a
delete can be undone.

Backed by SQLite rather than kept in memory: an in-memory hold makes undo
disappear the moment the server restarts, which is the wrong default for
a tool whose whole promise is remembering things. The payload is stored
as JSON in a TEXT column - both `DeletedConversation` and `RoadmapNode`
are small and evolving, and a JSON blob lets their shape change without
a migration every time a field is added.

Deliberately not a soft-delete column on the source tables: for
conversations, that would leave entries in Chroma where semantic recall
would keep surfacing content the user just deleted, which is worse than
losing an undo across a restart. The hold here is a copy, off to the
side, capped and pruned - not the live record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from mindtrail.organize.db import connect, now_iso
from mindtrail.organize.roadmaps import RoadmapNode

MAX_HELD = 10


@dataclass(frozen=True)
class DeletedConversation:
    conversation_id: str
    title: str
    project_id: str | None
    pinned: bool
    unread: bool
    entries: tuple  # (query, summary, sources, topic, key_facts, kind)


def _conversation_to_json(item: DeletedConversation) -> str:
    return json.dumps(
        {
            "conversation_id": item.conversation_id,
            "title": item.title,
            "project_id": item.project_id,
            "pinned": item.pinned,
            "unread": item.unread,
            "entries": item.entries,
        }
    )


def _conversation_from_json(raw: str) -> DeletedConversation:
    # JSON has no tuple type, so every list nested in `entries` comes back
    # a list too. Rebuild the exact shape `handle_delete_conversation`
    # put in: an outer tuple of per-entry tuples, each still holding its
    # `sources`/`key_facts` as lists, the same as before it was stored.
    data = json.loads(raw)
    return DeletedConversation(
        conversation_id=data["conversation_id"],
        title=data["title"],
        project_id=data["project_id"],
        pinned=data["pinned"],
        unread=data["unread"],
        entries=tuple(tuple(entry) for entry in data["entries"]),
    )


def _node_to_json(node: RoadmapNode) -> str:
    return json.dumps(
        {
            "id": node.id,
            "roadmap_id": node.roadmap_id,
            "title": node.title,
            "detail": node.detail,
            "status": node.status,
            "note": node.note,
            "x": node.x,
            "y": node.y,
            "depends_on": list(node.depends_on),
            "created_at": node.created_at,
            "due_date": node.due_date,
        }
    )


def _node_from_json(raw: str) -> RoadmapNode:
    data = json.loads(raw)
    return RoadmapNode(
        id=data["id"],
        roadmap_id=data["roadmap_id"],
        title=data["title"],
        detail=data["detail"],
        status=data["status"],
        note=data["note"],
        x=data["x"],
        y=data["y"],
        depends_on=tuple(data["depends_on"]),
        created_at=data["created_at"],
        due_date=data["due_date"],
    )


class Trash:
    """Keeps the most recent deleted conversations, oldest evicted first.

    A connection is opened per operation, matching the rest of `organize`
    - the chat server is threaded and sqlite3 connections are not
    thread-safe by default, so no lock is needed around a call that owns
    its own connection start to finish.
    """

    def __init__(self, path: str | None = None, max_held: int = MAX_HELD):
        self._path = path
        self._max = max_held

    def put(self, item: DeletedConversation) -> None:
        with connect(self._path) as conn:
            # Re-putting an id (shouldn't normally happen, but keeps the
            # invariant honest) replaces rather than duplicates, and the
            # fresh `seq` moves it to the end like `move_to_end` did.
            conn.execute(
                "DELETE FROM deleted_items WHERE item_id = ?",
                (item.conversation_id,),
            )
            conn.execute(
                "INSERT INTO deleted_items (item_id, payload, deleted_at) "
                "VALUES (?, ?, ?)",
                (item.conversation_id, _conversation_to_json(item), now_iso()),
            )
            conn.execute(
                "DELETE FROM deleted_items WHERE seq NOT IN "
                "(SELECT seq FROM deleted_items ORDER BY seq DESC LIMIT ?)",
                (self._max,),
            )

    def take(self, conversation_id: str) -> DeletedConversation | None:
        """Remove and return an item; undo is a one-shot operation."""
        with connect(self._path) as conn:
            row = conn.execute(
                "SELECT payload FROM deleted_items WHERE item_id = ?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "DELETE FROM deleted_items WHERE item_id = ?", (conversation_id,)
            )
        return _conversation_from_json(row["payload"])

    def __len__(self) -> int:
        with connect(self._path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM deleted_items"
            ).fetchone()["n"]


class NodeTrash:
    """Same hold as `Trash`, keyed by roadmap node id, in its own table.

    A `RoadmapNode` is self-contained - unlike a conversation, it has no
    entries living elsewhere - so the row itself is the payload; no
    wrapper dataclass needed. Restoring must reuse the original id:
    `RoadmapNodeStore.delete` leaves other nodes' `depends_on` pointing
    at it, and a fresh id would leave those edges dangling forever.
    """

    def __init__(self, path: str | None = None, max_held: int = MAX_HELD):
        self._path = path
        self._max = max_held

    def put(self, node: RoadmapNode) -> None:
        with connect(self._path) as conn:
            conn.execute("DELETE FROM deleted_nodes WHERE node_id = ?", (node.id,))
            conn.execute(
                "INSERT INTO deleted_nodes (node_id, payload, deleted_at) "
                "VALUES (?, ?, ?)",
                (node.id, _node_to_json(node), now_iso()),
            )
            conn.execute(
                "DELETE FROM deleted_nodes WHERE seq NOT IN "
                "(SELECT seq FROM deleted_nodes ORDER BY seq DESC LIMIT ?)",
                (self._max,),
            )

    def take(self, node_id: str) -> RoadmapNode | None:
        with connect(self._path) as conn:
            row = conn.execute(
                "SELECT payload FROM deleted_nodes WHERE node_id = ?", (node_id,)
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM deleted_nodes WHERE node_id = ?", (node_id,))
        return _node_from_json(row["payload"])

    def __len__(self) -> int:
        with connect(self._path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM deleted_nodes"
            ).fetchone()["n"]
