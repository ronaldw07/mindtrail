"""Model-assisted retrieval: parsing, ordering, and falling back when the model fails."""

import pytest

from mindtrail.llm import LLMError
from mindtrail.memory import retrieval
from mindtrail.memory.store import MemoryStore


class ScriptedLLM:
    """Returns each scripted reply in turn; an Exception instance is raised instead."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, user, max_tokens=900):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply

        class Completion:
            text = reply
        return Completion()


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(path=str(tmp_path / "chroma"), collection="retrieval_test")
    s.add("what is overfitting", "A model memorizes noise in training data and fails on new data.", [])
    s.add("what is regularization", "A penalty on weights keeps a model simple; L1 zeroes some weights.", [])
    s.add("how does quicksort work", "Pick a pivot, partition, recurse on both sides.", [])
    return s


def test_expand_adds_rewrites_and_a_passage_and_never_repeats_the_question():
    llm = ScriptedLLM('{"rewrites": ["why does a model fail on new data", "Q"], "passage": "It memorizes noise."}')
    assert retrieval.expand_query(llm, "Q") == ["Q", "why does a model fail on new data", "It memorizes noise."]


@pytest.mark.parametrize("reply", [LLMError("down"), "not json at all", '{"rewrites": "oops"}'])
def test_expand_falls_back_to_the_question(reply):
    assert retrieval.expand_query(ScriptedLLM(reply), "Q") == ["Q"]


def test_rerank_reorders_ignores_junk_numbers_and_keeps_skipped_entries(store):
    entries = store.all()[:3]
    llm = ScriptedLLM('{"ranking": [3, 99, 3, 1]}')           # out of range, repeated, and 2 skipped
    out = retrieval.rerank(llm, "q", entries)
    assert [e.id for e in out] == [entries[2].id, entries[0].id, entries[1].id]


def test_rerank_trims_to_k_and_leaves_order_alone_on_failure(store):
    entries = store.all()[:3]
    assert retrieval.rerank(ScriptedLLM(LLMError("x")), "q", entries, k=2) == entries[:2]
    assert retrieval.rerank(ScriptedLLM('{"ranking": "bad"}'), "q", entries) == entries
    assert retrieval.rerank(ScriptedLLM(), "q", entries[:1]) == entries[:1]   # nothing to compare, no call


def test_deep_search_finds_an_entry_the_plain_question_would_miss(store):
    llm = ScriptedLLM('{"rewrites": ["what is overfitting"], "passage": ""}', '{"ranking": [1, 2, 3]}')
    found = retrieval.deep_search(store, llm, "my model aces training but flops on unseen data", k=1)
    assert found[0].query == "what is overfitting"
    assert len(llm.prompts) == 2          # one expansion, one rerank


def test_deep_search_still_answers_when_the_model_is_down(store):
    llm = ScriptedLLM(LLMError("down"), LLMError("down"))
    found = retrieval.deep_search(store, llm, "how does quicksort work", k=1)
    assert found[0].query == "how does quicksort work"
