"""Undo for deleted conversations."""

import pytest

from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.trash import DeletedConversation, Trash
from mindtrail.web import api


@pytest.fixture
def store(tmp_path):
    return MemoryStore(path=str(tmp_path / "chroma"), collection="testcol")


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def chats(db):
    return ConversationStore(db)


@pytest.fixture
def projects(db):
    return ProjectStore(db)


def an_item(cid="c1"):
    return DeletedConversation(
        conversation_id=cid, title="t", project_id=None,
        pinned=False, unread=False, entries=(),
    )


# --- the holding area -------------------------------------------------


def test_an_item_can_be_taken_back():
    trash = Trash()
    trash.put(an_item())

    assert trash.take("c1") is not None


def test_taking_is_one_shot():
    trash = Trash()
    trash.put(an_item())
    trash.take("c1")

    assert trash.take("c1") is None, "undo should not be replayable"


def test_taking_something_absent_returns_none():
    assert Trash().take("nope") is None


def test_oldest_entries_are_evicted_past_the_limit():
    trash = Trash(max_held=2)
    trash.put(an_item("a"))
    trash.put(an_item("b"))
    trash.put(an_item("c"))

    assert trash.take("a") is None
    assert trash.take("c") is not None
    assert len(trash) == 1


# --- delete and restore through the API -------------------------------


def test_deleting_holds_the_conversation_for_undo(store, chats):
    trash = Trash()
    chat = chats.create("keep me")
    store.add("q", "a", [], conversation_id=chat.id)

    api.handle_delete_conversation(store, chats, chat.id, trash)

    assert len(trash) == 1


def test_undo_restores_the_chat_and_its_messages(store, chats):
    trash = Trash()
    chat = chats.create("important")
    store.add("q1", "answer one", ["http://a.com"], conversation_id=chat.id)
    store.add("q2", "answer two", [], conversation_id=chat.id)
    api.handle_delete_conversation(store, chats, chat.id, trash)

    result = api.handle_undo_delete(store, chats, trash, chat.id)

    assert result["entries"] == 2
    restored = chats.get(result["conversation_id"])
    assert restored.title == "important"
    assert [e.query for e in store.by_conversation(restored.id)] == ["q1", "q2"]


def test_undo_preserves_the_project_and_flags(store, chats, projects):
    trash = Trash()
    project = projects.create("Career")
    chat = chats.create("c", project_id=project.id)
    chats.set_pinned(chat.id, True)
    store.add("q", "a", [], conversation_id=chat.id)
    api.handle_delete_conversation(store, chats, chat.id, trash)

    result = api.handle_undo_delete(store, chats, trash, chat.id)

    restored = chats.get(result["conversation_id"])
    assert restored.project_id == project.id
    assert restored.pinned is True


def test_undo_preserves_entry_metadata(store, chats):
    trash = Trash()
    chat = chats.create("c")
    store.add("Document: cv.pdf", "text", [], topic="Career",
              key_facts=["f1"], kind="document", conversation_id=chat.id)
    api.handle_delete_conversation(store, chats, chat.id, trash)

    result = api.handle_undo_delete(store, chats, trash, chat.id)

    entry = store.by_conversation(result["conversation_id"])[0]
    assert entry.kind == "document"
    assert entry.topic == "Career"
    assert entry.key_facts == ("f1",)


def test_undo_after_the_window_reports_nothing_to_undo(store, chats):
    trash = Trash()

    assert "error" in api.handle_undo_delete(store, chats, trash, "never-existed")


def test_deleting_without_a_trash_still_works(store, chats):
    chat = chats.create("c")
    store.add("q", "a", [], conversation_id=chat.id)

    result = api.handle_delete_conversation(store, chats, chat.id)

    assert result["ok"] is True
    assert result["undoable"] is False
