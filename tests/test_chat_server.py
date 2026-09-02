"""Tests for the chat request logic. The socket server itself is glue and
is exercised by a live smoke test instead of a unit test, matching how
network I/O is treated elsewhere in this project.
"""

from mindtrail.ingest.researcher import Research
from mindtrail.memory.store import MemoryStore
from mindtrail.web.chat_server import (
    CHAT_HTML,
    handle_ask,
    handle_topic_entries,
    handle_topics,
)


class StubResearcher:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.last_query = None

    def research_and_store(self, query):
        self.last_query = query
        if self._error:
            raise self._error
        return self._result


def a_result(**overrides):
    defaults = dict(
        query="q", summary="the answer", sources=("http://a.com",), recalled=(), tokens=1
    )
    defaults.update(overrides)
    return Research(**defaults)


def a_store(tmp_path):
    return MemoryStore(path=str(tmp_path / "chroma"), collection="test")


def test_a_normal_message_returns_the_answer_and_sources(tmp_path):
    store = a_store(tmp_path)
    store.add("q", "the answer", ["http://a.com"], topic="Vector DBs")

    response = handle_ask(StubResearcher(a_result()), store, "what is X")

    assert response["answer"] == "the answer"
    assert response["sources"] == ["http://a.com"]
    assert response["recalled"] == []


def test_response_includes_the_assigned_topic(tmp_path):
    store = a_store(tmp_path)
    store.add("q", "a", [], topic="Docker")

    response = handle_ask(StubResearcher(a_result()), store, "what is X")

    assert response["topic"] == "Docker"


def test_recalled_entries_are_reduced_to_their_questions(tmp_path):
    from mindtrail.memory.store import Entry

    store = a_store(tmp_path)
    store.add("q", "a", [])
    recalled = (Entry(id="1", query="earlier q", summary="s", sources=(), created_at="t"),)

    response = handle_ask(StubResearcher(a_result(recalled=recalled)), store, "what is X")

    assert response["recalled"] == ["earlier q"]


def test_empty_message_is_rejected_without_calling_the_researcher(tmp_path):
    researcher = StubResearcher(a_result())

    response = handle_ask(researcher, a_store(tmp_path), "   ")

    assert "error" in response
    assert researcher.last_query is None


def test_a_failure_is_surfaced_as_an_error_field_not_raised(tmp_path):
    response = handle_ask(
        StubResearcher(error=ValueError("no sources")), a_store(tmp_path), "what is X"
    )

    assert response["error"] == "no sources"


def test_chat_html_references_the_api_endpoints():
    assert "/api/ask" in CHAT_HTML
    assert "/api/topics" in CHAT_HTML
    assert "/api/topic/" in CHAT_HTML


def test_topics_are_counted_and_sorted(tmp_path):
    store = a_store(tmp_path)
    store.add("q1", "a", [], topic="Docker")
    store.add("q2", "a", [], topic="Docker")
    store.add("q3", "a", [], topic="Kubernetes")

    response = handle_topics(store)

    assert response["topics"] == [
        {"name": "Docker", "count": 2},
        {"name": "Kubernetes", "count": 1},
    ]


def test_untopiced_entries_are_counted_as_uncategorized(tmp_path):
    store = a_store(tmp_path)
    store.add("q1", "a", [])

    response = handle_topics(store)

    assert response["topics"] == [{"name": "Uncategorized", "count": 1}]


def test_advice_entries_are_excluded_from_topic_counts(tmp_path):
    store = a_store(tmp_path)
    store.add("Advice", "a plan", [], topic="Advice", kind="advice")

    assert handle_topics(store)["topics"] == []


def test_topic_entries_are_returned_oldest_first(tmp_path):
    store = a_store(tmp_path)
    store.add("first", "a1", [], topic="Docker")
    store.add("second", "a2", [], topic="Docker")

    response = handle_topic_entries(store, "Docker")

    assert [e["query"] for e in response["entries"]] == ["first", "second"]


def test_topic_entries_only_include_the_requested_topic(tmp_path):
    store = a_store(tmp_path)
    store.add("q1", "a", [], topic="Docker")
    store.add("q2", "a", [], topic="Kubernetes")

    response = handle_topic_entries(store, "Docker")

    assert len(response["entries"]) == 1
    assert response["entries"][0]["query"] == "q1"


def test_unknown_topic_returns_no_entries(tmp_path):
    store = a_store(tmp_path)
    store.add("q1", "a", [], topic="Docker")

    assert handle_topic_entries(store, "Nonexistent")["entries"] == []
