"""Backfill conversations for entries that predate them.

Entries created before conversations existed carry a topic but no
conversation_id, so they would be invisible in a sidebar that lists
conversations. One conversation is created per existing topic, which
preserves what the topic-grouped view already showed.

Runs at startup and is a no-op once everything is assigned.
"""

from __future__ import annotations

from mindtrail.memory.store import UNCATEGORIZED, MemoryStore
from mindtrail.organize.conversations import ConversationStore

SKIPPED_KINDS = frozenset({"advice"})


def backfill_conversations(
    store: MemoryStore, conversations: ConversationStore
) -> int:
    """Assign a conversation to every entry missing one.

    Returns the number of conversations created.
    """
    orphans = [
        e
        for e in store.all()
        if not e.conversation_id and e.kind not in SKIPPED_KINDS
    ]
    if not orphans:
        return 0

    by_topic: dict[str, list] = {}
    for entry in orphans:
        by_topic.setdefault(entry.topic or UNCATEGORIZED, []).append(entry)

    for topic, entries in by_topic.items():
        conversation = conversations.create(title=topic)
        store.assign_conversation([e.id for e in entries], conversation.id)

    return len(by_topic)
