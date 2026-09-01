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
