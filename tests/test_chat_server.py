"""Tests for the chat request logic. The socket server itself is glue and
is exercised by a live smoke test instead of a unit test, matching how
network I/O is treated elsewhere in this project.
"""

from mindtrail.ingest.researcher import Research
from mindtrail.web.chat_server import CHAT_HTML, handle_ask


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


def test_a_normal_message_returns_the_answer_and_sources():
    response = handle_ask(StubResearcher(a_result()), "what is X")

    assert response["answer"] == "the answer"
    assert response["sources"] == ["http://a.com"]
    assert response["recalled"] == []


def test_recalled_entries_are_reduced_to_their_questions():
    from mindtrail.memory.store import Entry

    recalled = (Entry(id="1", query="earlier q", summary="s", sources=(), created_at="t"),)
    response = handle_ask(StubResearcher(a_result(recalled=recalled)), "what is X")

    assert response["recalled"] == ["earlier q"]


def test_empty_message_is_rejected_without_calling_the_researcher():
    researcher = StubResearcher(a_result())

    response = handle_ask(researcher, "   ")

    assert "error" in response
    assert researcher.last_query is None


def test_a_failure_is_surfaced_as_an_error_field_not_raised():
    response = handle_ask(StubResearcher(error=ValueError("no sources")), "what is X")

    assert response["error"] == "no sources"


def test_chat_html_references_the_api_endpoint():
    assert "/api/ask" in CHAT_HTML
