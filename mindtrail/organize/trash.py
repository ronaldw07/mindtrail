"""Short-lived hold for deleted conversations, so a delete can be undone.

Deliberately in memory and deliberately small. The alternative - a
soft-delete column - would leave the entries in Chroma where semantic
recall would keep surfacing content the user just deleted, which is
worse than losing an undo across a restart.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

MAX_HELD = 10


@dataclass(frozen=True)
class DeletedConversation:
    conversation_id: str
    title: str
    project_id: str | None
    pinned: bool
    unread: bool
    entries: tuple  # (query, summary, sources, topic, key_facts, kind)


class Trash:
    """Keeps the most recent deletions, oldest evicted first."""

    def __init__(self, max_held: int = MAX_HELD):
        self._items: OrderedDict[str, DeletedConversation] = OrderedDict()
        self._max = max_held
        self._lock = threading.Lock()

    def put(self, item: DeletedConversation) -> None:
        with self._lock:
            self._items[item.conversation_id] = item
            self._items.move_to_end(item.conversation_id)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def take(self, conversation_id: str) -> DeletedConversation | None:
        """Remove and return an item; undo is a one-shot operation."""
        with self._lock:
            return self._items.pop(conversation_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
