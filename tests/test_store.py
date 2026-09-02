"""Store tests. No network and no API key required."""

import pytest

from mindtrail.memory.store import MemoryStore


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


def test_kind_round_trips_through_storage(store):
    store.add("q", "a", [], kind="note")

    assert store.all()[0].kind == "note"
