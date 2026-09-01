"""Advice generation tests. The model is stubbed."""

import pytest

from mindtrail.advice.planner import generate_advice
from mindtrail.llm import Completion
from mindtrail.memory.store import Entry


class StubLLM:
    def __init__(self, text="a plan"):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=900):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=7, model="stub")


def an_entry(query, summary, kind):
    return Entry(
        id=query, query=query, summary=summary, sources=(), created_at="t", kind=kind
    )


def test_advice_is_generated_from_stored_entries():
    entries = [an_entry("Document: resume.pdf", "CS degree, TS experience", "document")]

    advice = generate_advice(StubLLM(), entries)

    assert advice.text == "a plan"


def test_documents_notes_and_research_are_all_included_in_the_prompt():
    entries = [
        an_entry("Document: resume.pdf", "resume content", "document"),
        an_entry("remember to follow up", "note content", "note"),
        an_entry("what is RAG", "research content", "research"),
    ]
    llm = StubLLM()

    generate_advice(llm, entries)

    assert "resume content" in llm.last_user_prompt
    assert "note content" in llm.last_user_prompt
    assert "research content" in llm.last_user_prompt


def test_advice_entries_are_excluded_from_their_own_input():
    # A previous advice run should not be fed back in as source material.
    entries = [an_entry("Advice", "old plan text", "advice")]

    with pytest.raises(ValueError):
        generate_advice(StubLLM(), entries)


def test_nothing_stored_raises_without_calling_the_model():
    llm = StubLLM()

    with pytest.raises(ValueError, match="nothing stored"):
        generate_advice(llm, [])

    assert llm.last_user_prompt is None


def test_long_summaries_are_capped_in_the_prompt():
    entries = [an_entry("Document: big.pdf", "x" * 5000, "document")]
    llm = StubLLM()

    generate_advice(llm, entries)

    assert len(llm.last_user_prompt) < 1000
