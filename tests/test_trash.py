"""Undo for deleted conversations and roadmap nodes."""

import pytest

from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.organize.trash import DeletedConversation, NodeTrash, Trash
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


@pytest.fixture
def trash(db):
    return Trash(db)


@pytest.fixture
def project_id(db):
    """A real project row, since roadmaps.project_id is a foreign key."""
    return ProjectStore(db).create("Career").id


@pytest.fixture
def roadmap_id(db, project_id):
    """A real roadmap row, since roadmap_nodes.roadmap_id is a foreign key."""
    return RoadmapStore(db).create("Goal", project_id=project_id).id


@pytest.fixture
def nodes(db):
    return RoadmapNodeStore(db)


@pytest.fixture
def node_trash(db):
    return NodeTrash(db)


def an_item(cid="c1", entries=()):
    return DeletedConversation(
        conversation_id=cid, title="t", project_id=None,
        pinned=False, unread=False, entries=entries,
    )


# --- the holding area: conversations -----------------------------------


def test_an_item_can_be_taken_back(trash):
    trash.put(an_item())

    assert trash.take("c1") is not None


def test_taking_is_one_shot(trash):
    trash.put(an_item())
    trash.take("c1")

    assert trash.take("c1") is None, "undo should not be replayable"


def test_taking_something_absent_returns_none(trash):
    assert trash.take("nope") is None


def test_oldest_entries_are_evicted_past_the_limit(db):
    trash = Trash(db, max_held=2)
    trash.put(an_item("a"))
    trash.put(an_item("b"))
    trash.put(an_item("c"))

    assert trash.take("a") is None
    assert trash.take("c") is not None
    assert len(trash) == 1


def test_round_trip_preserves_exact_types_including_unicode(trash):
    entries = (
        ("q1", "summary one", ["http://a.com"], "Career", ["f1", "f2"], "chat"),
        ("café ☕ résumé", "日本語のテキスト — emoji 🎯", [], "Übersicht", [], "note"),
    )
    trash.put(an_item("multi", entries=entries))

    held = trash.take("multi")

    assert isinstance(held.entries, tuple)
    assert all(isinstance(entry, tuple) for entry in held.entries)
    assert held.entries == entries
    assert held.entries[1][0] == "café ☕ résumé"
    assert held.entries[1][1] == "日本語のテキスト — emoji 🎯"
    assert held.entries[1][3] == "Übersicht"


def test_persists_across_a_new_trash_instance_on_the_same_database(db):
    """The whole point of moving off the in-memory OrderedDict: a
    restart constructs a fresh Trash, and undo must still work."""
    Trash(db).put(an_item("survivor", entries=(("q", "a", [], "t", [], "chat"),)))

    reopened = Trash(db)  # stands in for the process restarting

    held = reopened.take("survivor")
    assert held is not None
    assert held.conversation_id == "survivor"
    assert held.entries == (("q", "a", [], "t", [], "chat"),)
    assert reopened.take("survivor") is None, "still one-shot after reopening"


# --- delete and restore through the API: conversations ------------------


def test_deleting_holds_the_conversation_for_undo(store, chats, trash):
    chat = chats.create("keep me")
    store.add("q", "a", [], conversation_id=chat.id)

    api.handle_delete_conversation(store, chats, chat.id, trash)

    assert len(trash) == 1


def test_undo_restores_the_chat_and_its_messages(store, chats, trash):
    chat = chats.create("important")
    store.add("q1", "answer one", ["http://a.com"], conversation_id=chat.id)
    store.add("q2", "answer two", [], conversation_id=chat.id)
    api.handle_delete_conversation(store, chats, chat.id, trash)

    result = api.handle_undo_delete(store, chats, trash, chat.id)

    assert result["entries"] == 2
    restored = chats.get(result["conversation_id"])
    assert restored.title == "important"
    assert [e.query for e in store.by_conversation(restored.id)] == ["q1", "q2"]


def test_undo_preserves_the_project_and_flags(store, chats, projects, trash):
    project = projects.create("Career")
    chat = chats.create("c", project_id=project.id)
    chats.set_pinned(chat.id, True)
    store.add("q", "a", [], conversation_id=chat.id)
    api.handle_delete_conversation(store, chats, chat.id, trash)

    result = api.handle_undo_delete(store, chats, trash, chat.id)

    restored = chats.get(result["conversation_id"])
    assert restored.project_id == project.id
    assert restored.pinned is True


def test_undo_preserves_entry_metadata(store, chats, trash):
    chat = chats.create("c")
    store.add("Document: cv.pdf", "text", [], topic="Career",
              key_facts=["f1"], kind="document", conversation_id=chat.id)
    api.handle_delete_conversation(store, chats, chat.id, trash)

    result = api.handle_undo_delete(store, chats, trash, chat.id)

    entry = store.by_conversation(result["conversation_id"])[0]
    assert entry.kind == "document"
    assert entry.topic == "Career"
    assert entry.key_facts == ("f1",)


def test_undo_after_the_window_reports_nothing_to_undo(store, chats, trash):
    assert "error" in api.handle_undo_delete(store, chats, trash, "never-existed")


def test_deleting_without_a_trash_still_works(store, chats):
    chat = chats.create("c")
    store.add("q", "a", [], conversation_id=chat.id)

    result = api.handle_delete_conversation(store, chats, chat.id)

    assert result["ok"] is True
    assert result["undoable"] is False


# --- the holding area: roadmap nodes -------------------------------------


def test_a_node_can_be_taken_back(nodes, node_trash, roadmap_id):
    node = nodes.add(roadmap_id, "Step")
    node_trash.put(node)

    held = node_trash.take(node.id)

    assert held == node, "restore must reproduce the exact node, id included"


def test_taking_a_node_is_one_shot(nodes, node_trash, roadmap_id):
    node = nodes.add(roadmap_id, "Step")
    node_trash.put(node)
    node_trash.take(node.id)

    assert node_trash.take(node.id) is None


def test_node_trash_evicts_the_oldest_past_the_limit(db, nodes, roadmap_id):
    small = NodeTrash(db, max_held=2)
    a = nodes.add(roadmap_id, "A")
    b = nodes.add(roadmap_id, "B")
    c = nodes.add(roadmap_id, "C")
    small.put(a)
    small.put(b)
    small.put(c)

    assert small.take(a.id) is None
    assert small.take(c.id) is not None
    assert len(small) == 1


def test_node_trash_persists_across_a_new_instance_on_the_same_database(db, nodes, roadmap_id):
    node = nodes.add(roadmap_id, "Persisted step")
    NodeTrash(db).put(node)

    reopened = NodeTrash(db)  # stands in for the process restarting

    held = reopened.take(node.id)
    assert held == node


# --- delete and restore through the API: roadmap nodes -------------------


def test_deleting_a_node_holds_it_for_undo(nodes, node_trash, roadmap_id):
    node = nodes.add(roadmap_id, "Step")

    result = api.handle_delete_node(nodes, node.id, node_trash)

    assert result["ok"] is True
    assert result["undoable"] is True
    assert nodes.get(node.id) is None
    assert len(node_trash) == 1


def test_undo_restores_a_deleted_node_under_its_original_id_and_edges(
    nodes, node_trash, roadmap_id
):
    """The critical property: RoadmapNodeStore.delete leaves other nodes'
    depends_on pointing at the deleted id, so the restore only fixes
    those edges if the node comes back under the same id."""
    base = nodes.add(roadmap_id, "Base")
    dependent = nodes.add(roadmap_id, "Depends on base", depends_on=[base.id])

    api.handle_delete_node(nodes, base.id, node_trash)
    assert base.id in nodes.get(dependent.id).depends_on, "dangling by design"

    result = api.handle_undo_delete_node(nodes, node_trash, base.id)

    assert result["ok"] is True
    restored = nodes.get(base.id)
    assert restored is not None
    assert restored.id == base.id
    assert base.id in nodes.get(dependent.id).depends_on


def test_undo_for_a_node_never_deleted_reports_nothing_to_undo(nodes, node_trash):
    assert "error" in api.handle_undo_delete_node(nodes, node_trash, "never-existed")


def test_deleting_a_node_without_a_trash_still_works(nodes, roadmap_id):
    node = nodes.add(roadmap_id, "Step")

    result = api.handle_delete_node(nodes, node.id)

    assert result["ok"] is True
    assert result["undoable"] is False
