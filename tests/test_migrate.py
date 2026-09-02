"""Backfill of conversations for pre-existing entries."""

import pytest

from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.migrate import backfill_conversations


@pytest.fixture
def store(tmp_path):
    return MemoryStore(path=str(tmp_path / "chroma"), collection="testcol")


@pytest.fixture
def chats(tmp_path):
    path = str(tmp_path / "test.db")
    initialize(path)
    return ConversationStore(path)


def test_entries_sharing_a_topic_join_one_conversation(store, chats):
    store.add("q1", "a1", [], topic="Docker")
    store.add("q2", "a2", [], topic="Docker")

    created = backfill_conversations(store, chats)

    assert created == 1
    assert len({e.conversation_id for e in store.all()}) == 1


def test_different_topics_get_separate_conversations(store, chats):
    store.add("q1", "a1", [], topic="Docker")
    store.add("q2", "a2", [], topic="Kubernetes")

    assert backfill_conversations(store, chats) == 2


def test_conversation_is_titled_after_the_topic(store, chats):
    store.add("q1", "a1", [], topic="Docker")

    backfill_conversations(store, chats)

    assert [c.title for c in chats.all()] == ["Docker"]


def test_untopiced_entries_go_to_uncategorized(store, chats):
    store.add("q1", "a1", [])

    backfill_conversations(store, chats)

    assert [c.title for c in chats.all()] == ["Uncategorized"]


def test_backfill_is_idempotent(store, chats):
    store.add("q1", "a1", [], topic="Docker")

    first = backfill_conversations(store, chats)
    second = backfill_conversations(store, chats)

    assert first == 1
    assert second == 0, "a second run must not create duplicate conversations"


def test_entries_already_assigned_are_left_alone(store, chats):
    store.add("q1", "a1", [], topic="Docker", conversation_id="existing-id")

    assert backfill_conversations(store, chats) == 0
    assert store.all()[0].conversation_id == "existing-id"


def test_advice_entries_are_not_given_conversations(store, chats):
    store.add("Advice", "a plan", [], topic="Advice", kind="advice")

    assert backfill_conversations(store, chats) == 0


def test_empty_store_is_a_no_op(store, chats):
    assert backfill_conversations(store, chats) == 0
