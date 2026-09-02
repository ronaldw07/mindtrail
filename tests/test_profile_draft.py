"""Profile drafting tests. The model is stubbed."""

import pytest

from mindtrail.advice.profile_draft import draft_profile
from mindtrail.llm import Completion
from mindtrail.memory.store import Entry


class StubLLM:
    def __init__(self, text="drafted profile text"):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=500):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=5, model="stub")


def an_entry(query, summary="s", kind="document"):
    return Entry(id=query, query=query, summary=summary, sources=(), created_at="t", kind=kind)


def test_draft_uses_documents_and_notes():
    llm = StubLLM()

    draft_profile(llm, [an_entry("Document: resume.pdf", "CS, TypeScript, React")])

    assert "CS, TypeScript, React" in llm.last_user_prompt


def test_research_entries_are_excluded():
    llm = StubLLM()

    draft_profile(llm, [
        an_entry("Document: resume.pdf", "real content"),
        an_entry("what is a hash table", "unrelated research", kind="research"),
    ])

    assert "unrelated research" not in llm.last_user_prompt


def test_no_documents_or_notes_raises_without_calling_the_model():
    llm = StubLLM()

    with pytest.raises(ValueError):
        draft_profile(llm, [an_entry("q", kind="research")])

    assert llm.last_user_prompt is None


def test_draft_text_is_returned():
    assert draft_profile(StubLLM("A CS student."), [an_entry("Document: r.pdf")]) == "A CS student."
