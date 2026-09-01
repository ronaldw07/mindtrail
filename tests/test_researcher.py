"""Researcher tests. The LLM and the network are both stubbed."""

import pytest

from mindtrail.ingest.researcher import Researcher, _format_prior
from mindtrail.ingest.search import SearchError, SearchResult
from mindtrail.ingest.topic import TopicAssignment
from mindtrail.llm import Completion
from mindtrail.memory.store import MemoryStore


class StubLLM:
    def __init__(self, text="A synthesized answer."):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=900):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=42, model="stub")


class StubProvider:
    def __init__(self, results):
        self._results = results

    def search(self, query, max_results):
        return self._results[:max_results]


@pytest.fixture
def store(tmp_path):
    return MemoryStore(path=str(tmp_path / "chroma"), collection="test")


@pytest.fixture
def provider():
    return StubProvider(
        [SearchResult(title="T", url="http://a.com", snippet="A useful snippet.")]
    )


def test_research_returns_summary_and_sources(store, provider):
    result = Researcher(store, provider, StubLLM()).research("what is X")

    assert result.summary == "A synthesized answer."
    assert result.sources == ("http://a.com",)


def test_unreachable_page_falls_back_to_the_search_snippet(store, provider):
    llm = StubLLM()

    Researcher(store, provider, llm).research("what is X")

    # http://a.com is not fetchable in tests, so the snippet must appear.
    assert "A useful snippet." in llm.last_user_prompt


def test_research_and_store_persists_the_entry(store, provider):
    researcher = Researcher(store, provider, StubLLM())

    researcher.research_and_store("what is X")

    assert store.count() == 1


def test_prior_research_is_injected_into_the_prompt(store, provider):
    store.add("what is a vector database", "It stores embeddings.", [])
    llm = StubLLM()

    Researcher(store, provider, llm).research("how do vector databases scale")

    assert "PRIOR RESEARCH" in llm.last_user_prompt
    assert "It stores embeddings." in llm.last_user_prompt


def test_first_question_has_no_prior_research_section(store, provider):
    llm = StubLLM()

    Researcher(store, provider, llm).research("a brand new topic")

    assert "PRIOR RESEARCH" not in llm.last_user_prompt


def test_no_usable_sources_raises(store):
    empty = StubProvider([])

    with pytest.raises(SearchError):
        Researcher(store, empty, StubLLM()).research("what is X")


def test_format_prior_is_empty_without_entries():
    assert _format_prior([]) == ""


class StubTopicExtractor:
    def __init__(self, assignment=None, error=None):
        self._assignment = assignment or TopicAssignment("Topic", ("fact",))
        self._error = error

    def extract(self, query, summary, existing_topics):
        if self._error:
            raise self._error
        return self._assignment


def test_topic_and_key_facts_are_stored_when_extractor_is_given(store, provider):
    researcher = Researcher(
        store, provider, StubLLM(), topic_extractor=StubTopicExtractor()
    )

    researcher.research_and_store("what is X")

    assert store.all()[0].topic == "Topic"
    assert store.all()[0].key_facts == ("fact",)


def test_without_an_extractor_entries_have_no_topic(store, provider):
    researcher = Researcher(store, provider, StubLLM())

    researcher.research_and_store("what is X")

    assert store.all()[0].topic == ""


def test_a_failed_topic_extraction_does_not_lose_the_research(store, provider):
    researcher = Researcher(
        store,
        provider,
        StubLLM(),
        topic_extractor=StubTopicExtractor(error=ValueError("bad json")),
    )

    researcher.research_and_store("what is X")

    assert store.count() == 1
    assert store.all()[0].topic == ""
