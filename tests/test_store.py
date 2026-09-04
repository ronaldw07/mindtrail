"""Store tests. No network and no API key required."""

import pytest

from mindtrail.memory.store import CHUNK_CHARS, MemoryStore, _chunk_text
from mindtrail.web import api


@pytest.fixture
def store(tmp_path):
    return MemoryStore(path=str(tmp_path / "chroma"), collection="test")


def test_added_entry_round_trips_through_search(store):
    store.add("what is a vector database", "A store for embeddings.", ["http://a.com"])

    found = store.search("vector database", k=1)

    assert len(found) == 1
    assert found[0].query == "what is a vector database"
    assert found[0].sources == ("http://a.com",)


def test_search_ranks_the_semantically_closer_entry_first(store):
    store.add("how do I bake sourdough bread", "Use a starter.", [])
    store.add("what is a vector database", "A store for embeddings.", [])

    found = store.search("embedding storage for retrieval", k=2)

    assert found[0].query == "what is a vector database"


def test_recent_returns_newest_first(store):
    store.add("first question", "one", [])
    store.add("second question", "two", [])

    assert [e.query for e in store.recent(2)] == ["second question", "first question"]


def test_search_on_empty_store_returns_nothing(store):
    assert store.search("anything") == []


def test_search_caps_results_at_what_exists(store):
    store.add("only entry", "text", [])

    assert len(store.search("entry", k=10)) == 1


def test_empty_query_is_rejected(store):
    with pytest.raises(ValueError):
        store.add("   ", "summary", [])


def test_empty_summary_is_rejected(store):
    with pytest.raises(ValueError):
        store.add("query", "", [])


@pytest.mark.parametrize("k", [0, -5])
def test_non_positive_k_still_returns_a_result(store, k):
    # Chroma rejects n_results <= 0, so the floor is applied before it.
    store.add("only entry", "text", [])

    assert len(store.search("entry", k=k)) == 1


@pytest.mark.parametrize("n", [0, -1])
def test_non_positive_recent_count_still_returns_a_result(store, n):
    store.add("only entry", "text", [])

    assert len(store.recent(n)) == 1


def test_entries_are_immutable(store):
    entry = store.add("a question", "original", [])

    updated = entry.with_summary("changed")

    assert entry.summary == "original"
    assert updated.summary == "changed"


def test_topic_and_key_facts_round_trip(store):
    entry = store.add(
        "what is a vector database",
        "It stores embeddings.",
        [],
        topic="Vector Databases",
        key_facts=["fact one", "fact two"],
    )

    assert entry.topic == "Vector Databases"
    assert entry.key_facts == ("fact one", "fact two")
    assert store.all()[0].key_facts == ("fact one", "fact two")


def test_entries_without_a_topic_default_to_empty(store):
    entry = store.add("q", "a", [])
    assert entry.topic == ""
    assert entry.key_facts == ()


def test_topics_lists_distinct_labels_in_use(store):
    store.add("q1", "a1", [], topic="Docker")
    store.add("q2", "a2", [], topic="Docker")
    store.add("q3", "a3", [], topic="Kubernetes")
    store.add("q4", "a4", [])  # no topic

    assert store.topics() == ["Docker", "Kubernetes"]


def test_all_returns_every_entry_newest_first(store):
    store.add("first", "a", [])
    store.add("second", "a", [])

    entries = store.all()

    assert [e.query for e in entries] == ["second", "first"]


def test_all_on_empty_store_returns_nothing(store):
    assert store.all() == []


def test_kind_defaults_to_research(store):
    entry = store.add("q", "a", [])

    assert entry.kind == "research"


def test_summary_does_not_duplicate_the_query_on_read_back(store):
    # The embedded document is "query\n\nsummary"; reading a stored entry
    # back must return the summary alone, not that concatenation.
    store.add("what is a vector database", "It stores embeddings.", [])

    entry = store.all()[0]

    assert entry.summary == "It stores embeddings."
    assert entry.query not in entry.summary


def test_entries_are_grouped_by_conversation_oldest_first(store):
    store.add("first", "a", [], conversation_id="c1")
    store.add("second", "a", [], conversation_id="c1")
    store.add("other", "a", [], conversation_id="c2")

    assert [e.query for e in store.by_conversation("c1")] == ["first", "second"]


def test_by_conversation_with_no_id_returns_nothing(store):
    store.add("q", "a", [], conversation_id="c1")

    assert store.by_conversation("") == []


def test_deleting_a_conversation_removes_only_its_entries(store):
    store.add("doomed", "a", [], conversation_id="c1")
    store.add("survivor", "a", [], conversation_id="c2")

    removed = store.delete_conversation_entries("c1")

    assert removed == 1
    assert [e.query for e in store.all()] == ["survivor"]


def test_assigning_a_conversation_preserves_other_metadata(store):
    # Chroma merges metadata on update; a regression here would silently
    # wipe topic/kind off migrated entries.
    entry = store.add("q", "a", [], topic="Docker", key_facts=["f"], kind="note")

    store.assign_conversation([entry.id], "c1")

    migrated = store.all()[0]
    assert migrated.conversation_id == "c1"
    assert migrated.topic == "Docker"
    assert migrated.kind == "note"
    assert migrated.key_facts == ("f",)


def test_kind_round_trips_through_storage(store):
    store.add("q", "a", [], kind="note")

    assert store.all()[0].kind == "note"


# --- recall provenance ------------------------------------------------


def test_entries_default_to_no_recalled_ids(store):
    entry = store.add("q", "a", [])

    assert entry.recalled_ids == ()


def test_recalled_ids_round_trip(store):
    base = store.add("base entry", "a", [])
    followup = store.add("followup", "b", [], recalled_ids=[base.id])

    reloaded = next(e for e in store.all() if e.id == followup.id)
    assert reloaded.recalled_ids == (base.id,)


def test_get_returns_a_single_entry_by_id(store):
    entry = store.add("q", "a", [], topic="Docker")

    found = store.get(entry.id)

    assert found is not None
    assert found.query == "q"
    assert found.topic == "Docker"


def test_get_on_a_missing_id_returns_none(store):
    assert store.get("nope") is None


def test_get_works_on_a_long_chunked_entry(store):
    long_summary = "Filler content repeated many times. " * 60
    entry = store.add("long entry", long_summary, [])

    found = store.get(entry.id)

    assert found is not None
    assert found.summary == long_summary


# --- chunking (long entries split into multiple embedded vectors) --------


def test_chunk_text_leaves_short_text_alone():
    assert _chunk_text("short") == ["short"]


def test_chunk_text_splits_long_text():
    long_text = "Sentence one. " * 200

    chunks = _chunk_text(long_text)

    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_CHARS for c in chunks)


def test_a_long_entry_is_stored_as_multiple_chroma_rows(store):
    long_summary = "Filler sentence about nothing important. " * 60
    entry = store.add("q", long_summary, [])

    raw = store._collection.get()
    rows = [
        rid for rid in raw["ids"]
        if rid == entry.id or rid.startswith(entry.id + "::chunk")
    ]
    assert len(rows) > 1


def test_search_finds_content_only_present_in_a_later_chunk(store):
    # A distinctive phrase placed after enough filler that it would sit
    # past the embedder's 256-token truncation point in a single vector -
    # this is the exact failure a single-vector store would have.
    filler = "This paragraph discusses ordinary background material. " * 40
    long_summary = filler + "The secret keyword is zylophonic."
    store.add("a very long entry", long_summary, [])
    store.add("an unrelated short entry", "This is about gardening and plants.", [])

    found = store.search("zylophonic", k=1)

    assert len(found) == 1
    assert found[0].query == "a very long entry"


def test_search_does_not_return_the_same_entry_twice_from_multiple_chunks(store):
    long_summary = "Filler content repeated many times. " * 60
    store.add("long entry", long_summary, [])
    store.add("other entry", "something else entirely", [])

    found = store.search("filler content repeated", k=5)

    ids = [e.id for e in found]
    assert len(ids) == len(set(ids))


def test_all_counts_a_long_entry_once(store):
    long_summary = "Filler content repeated many times. " * 60
    store.add("long entry", long_summary, [])

    assert len(store.all()) == 1


def test_count_reflects_entries_not_chunk_rows(store):
    long_summary = "Filler content repeated many times. " * 60
    store.add("long entry", long_summary, [])
    store.add("short entry", "short", [])

    assert store.count() == 2


def test_deleting_a_conversation_removes_every_chunk_of_a_long_entry(store):
    long_summary = "Filler content repeated many times. " * 60
    entry = store.add("long entry", long_summary, [], conversation_id="c1")

    removed = store.delete_conversation_entries("c1")

    assert removed == 1
    raw = store._collection.get()
    assert entry.id not in raw["ids"]
    assert not any(rid.startswith(entry.id + "::chunk") for rid in raw["ids"])


def test_assigning_a_conversation_updates_every_chunk(store):
    long_summary = "Filler content repeated many times. " * 60
    entry = store.add("long entry", long_summary, [])

    store.assign_conversation([entry.id], "c1")

    raw = store._collection.get()
    for meta in raw["metadatas"]:
        if meta.get("parent_id") == entry.id:
            assert meta["conversation_id"] == "c1"


# --- reindexing pre-chunking entries --------------------------------------


def _legacy_row(store, entry_id, query="q", summary="s", **overrides):
    """Writes a row the way the store did before chunking existed - no
    is_chunk or parent_id metadata."""
    meta = {
        "query": query, "summary": summary, "sources": "",
        "created_at": "2020-01-01T00:00:00+00:00", "topic": "",
        "key_facts": "", "kind": "research", "conversation_id": "",
    }
    meta.update(overrides)
    store._collection.add(
        ids=[entry_id], documents=[f"{query}\n\n{summary}"], metadatas=[meta]
    )


def test_reindex_is_a_noop_when_nothing_is_legacy(store):
    store.add("q", "a", [])

    assert store.reindex_legacy_entries() == 0


def test_reindex_migrates_a_pre_chunking_row(store):
    _legacy_row(store, "legacy-1", query="old question", summary="old summary")

    migrated = store.reindex_legacy_entries()

    assert migrated == 1
    entries = store.all()
    assert len(entries) == 1
    assert entries[0].id == "legacy-1"
    assert entries[0].query == "old question"


def test_reindexing_preserves_the_original_id_and_conversation(store):
    _legacy_row(store, "legacy-2", conversation_id="c1")

    store.reindex_legacy_entries()

    assert store.all()[0].id == "legacy-2"
    assert store.by_conversation("c1")[0].id == "legacy-2"


def test_reindexing_a_long_legacy_entry_splits_it_into_chunks(store):
    long_summary = "Filler content repeated many times. " * 60
    _legacy_row(store, "legacy-3", summary=long_summary)

    store.reindex_legacy_entries()

    raw = store._collection.get()
    rows = [
        rid for rid in raw["ids"]
        if rid == "legacy-3" or rid.startswith("legacy-3::chunk")
    ]
    assert len(rows) > 1


def test_reindex_is_idempotent(store):
    _legacy_row(store, "legacy-4")

    first = store.reindex_legacy_entries()
    second = store.reindex_legacy_entries()

    assert first == 1
    assert second == 0


# --- single-entry delete and edit (G3) ------------------------------------


def test_deleting_a_single_entry_leaves_its_siblings_intact(store):
    doomed = store.add("bad research", "wrong answer", [])
    survivor = store.add("good research", "right answer", [])

    removed = store.delete_entry(doomed.id)

    assert removed is True
    assert [e.id for e in store.all()] == [survivor.id]


def test_deleting_a_missing_entry_returns_false(store):
    assert store.delete_entry("nope") is False


def test_deleting_a_long_entry_removes_every_chunk(store):
    long_summary = "Filler content repeated many times. " * 60
    entry = store.add("long entry", long_summary, [])

    assert store.delete_entry(entry.id) is True

    raw = store._collection.get()
    assert entry.id not in raw["ids"]
    assert not any(rid.startswith(entry.id + "::chunk") for rid in raw["ids"])


def test_editing_a_missing_entry_returns_none(store):
    assert store.update_entry("nope", summary="new text") is None


def test_editing_to_empty_text_is_rejected(store):
    entry = store.add("q", "a", [])

    with pytest.raises(ValueError):
        store.update_entry(entry.id, summary="   ")


def test_edit_preserves_the_id_and_untouched_fields(store):
    entry = store.add("q", "original", ["http://a.com"], topic="Docker", kind="note")

    updated = store.update_entry(entry.id, summary="revised")

    assert updated.id == entry.id
    assert updated.query == "q"
    assert updated.topic == "Docker"
    assert updated.kind == "note"
    assert updated.sources == ("http://a.com",)
    assert updated.summary == "revised"


def test_edit_re_embeds_and_is_findable_by_the_new_text(store):
    # The whole trap this task is about: a plain metadata swap would
    # leave the old vector in place, so search for the new wording would
    # still fail even though the UI shows it. This edits an entry to
    # something semantically far from the original, then proves the new
    # text - not the old - is what recall now matches.
    entry = store.add(
        "what is a vector database",
        "A vector database stores embeddings for similarity search.",
        [],
    )
    store.add("unrelated filler", "This entry is about baking sourdough bread.", [])

    store.update_entry(
        entry.id,
        query="how do I roast coffee beans",
        summary="Light roast coffee beans at a lower temperature for a shorter time.",
    )

    found = store.search("roasting coffee beans at home", k=1)
    assert found[0].id == entry.id
    assert found[0].summary == (
        "Light roast coffee beans at a lower temperature for a shorter time."
    )


def test_edit_removes_the_old_document_text_from_the_index(store):
    entry = store.add("original question", "original answer text", [])

    store.update_entry(entry.id, query="different question", summary="different answer text")

    raw = store._collection.get()
    assert "original answer text" not in raw["documents"]


# --- single-entry delete and edit through the API (G3) --------------------


def test_handle_delete_entry_removes_it(store):
    entry = store.add("q", "a", [])

    result = api.handle_delete_entry(store, entry.id)

    assert result == {"ok": True}
    assert store.get(entry.id) is None


def test_handle_delete_entry_on_a_missing_id_returns_an_error(store):
    assert api.handle_delete_entry(store, "nope") == {"error": "no such entry"}


def test_handle_update_entry_applies_only_the_summary(store):
    entry = store.add("q", "old summary", [])

    result = api.handle_update_entry(store, entry.id, {"summary": "new summary"})

    assert result["summary"] == "new summary"
    assert result["query"] == "q"


def test_handle_update_entry_on_a_missing_id_returns_the_documented_error(store):
    assert api.handle_update_entry(store, "nope", {"summary": "x"}) == {
        "error": "no such entry"
    }


def test_handle_update_entry_rejects_blank_text(store):
    entry = store.add("q", "a", [])

    result = api.handle_update_entry(store, entry.id, {"summary": "   "})

    assert "error" in result
