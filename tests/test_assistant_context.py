"""What the journey assistant reads besides the journey: matching saved
documents, and files sent with a message."""

import base64
from types import SimpleNamespace

import pytest

from mindtrail.advice import attachments
from mindtrail.advice.assistant_context import ATTACH_CHARS, DOC_CHARS, document_notes, with_attachments
from mindtrail.llm import LLMError
from mindtrail.web import assistant_files_api


class FakeStore:
    def __init__(self, entries=()):
        self.entries, self.added, self.queries = list(entries), [], []

    def search(self, query, k=3):
        self.queries.append(query)
        return self.entries[:k]

    def add(self, query, summary, sources, kind=""):
        self.added.append((query, summary, kind))


class SeeingLLM:
    def __init__(self, seen="Offer letter: Stripe, SWE intern, starts June 2027"):
        self.seen = seen

    def describe_image(self, prompt, image, mime):
        if self.seen is None:
            raise LLMError("Reading screenshots needs a GEMINI_API_KEY in .env.")
        return self.seen


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_matching_documents_are_added_trimmed_and_named():
    resume = SimpleNamespace(query="Document: resume.pdf", summary="FrameLight iOS app. " * 200)
    store = FakeStore([resume])

    notes = document_notes(store, "suggest goals Apply for summer internships")

    assert "[Document: resume.pdf] FrameLight iOS app." in notes
    assert len(notes.split("] ", 1)[1]) <= DOC_CHARS
    assert store.queries == ["suggest goals Apply for summer internships"]


def test_no_store_nothing_found_or_a_failing_search_adds_nothing():
    class Broken(FakeStore):
        def search(self, query, k=3):
            raise RuntimeError("chroma down")

    assert document_notes(None, "x") == document_notes(FakeStore(), "x") == document_notes(Broken(), "x") == ""


def test_sent_files_reach_the_model_but_the_chat_keeps_just_their_names():
    model, saved = with_attachments("What should I fix?", [{"name": "resume.pdf", "text": "x" * (ATTACH_CHARS + 50)}])

    assert model.startswith("What should I fix?") and "--- resume.pdf ---" in model
    assert model.split("--- resume.pdf ---\n")[1] == "x" * ATTACH_CHARS
    assert saved == "What should I fix?\n📎 resume.pdf"
    assert with_attachments("hi", "not a list") == ("hi", "hi")
    assert with_attachments("", [{"name": "shot.png", "text": "a chart"}])[1].startswith("Here's what I sent.")


@pytest.mark.parametrize("name, kind", [("Shot 1.PNG", "image"), ("resume.pdf", "pdf"), ("notes.md", "text"),
                                        ("song.mp3", ""), ("noext", "")])
def test_file_kinds(name, kind):
    assert attachments.kind_of(name) == kind


def test_a_screenshot_is_read_but_not_kept_in_memory():
    store = FakeStore()

    res = assistant_files_api.handle_attach(store, SeeingLLM(), {"name": "offer.png", "data": b64(b"\x89PNG...")})

    assert (res["kind"], res["saved"]) == ("image", False) and "Stripe" in res["text"]
    assert store.added == []


def test_a_text_file_is_read_and_kept_in_memory_for_later_chats():
    store = FakeStore()

    res = assistant_files_api.handle_attach(store, SeeingLLM(), {"name": "prefs.md", "data": b64(b"Want AI/ML roles in SF")})

    assert res["saved"] is True and res["text"] == "Want AI/ML roles in SF"
    assert store.added == [("Document: prefs.md", "Want AI/ML roles in SF", "document")]


@pytest.mark.parametrize("body, says", [
    ({"name": "song.mp3", "data": b64(b"x")}, "screenshot or photo"),
    ({"name": "a.txt", "data": "not base64!!"}, "didn't arrive intact"),
    ({"name": "a.txt", "data": ""}, "empty"),
    ({"name": "shot.png", "data": b64(b"x")}, "GEMINI_API_KEY"),
])
def test_unreadable_files_say_why(body, says):
    res = assistant_files_api.handle_attach(FakeStore(), SeeingLLM(seen=None), body)
    assert says in res["error"]


def test_files_over_the_size_limit_are_refused(monkeypatch):
    monkeypatch.setattr(attachments, "MAX_BYTES", 4)
    assert "MB" in assistant_files_api.handle_attach(FakeStore(), SeeingLLM(), {"name": "a.txt", "data": b64(b"12345")})["error"]
