"""Chat request handlers. Pure functions, no socket and no API key.

The HTTP plumbing in chat_server.py is glue and is exercised by a live
smoke test instead, matching how network I/O is treated elsewhere here.
"""

import pytest

from mindtrail.ingest.researcher import Research
from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.projects import ProjectStore
from mindtrail.web import api
from mindtrail.web.chat_ui import CHAT_HTML


class StubResearcher:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.last_conversation_id = None

    def research_and_store(self, query, conversation_id="", instructions=""):
        self.last_conversation_id = conversation_id
        self.last_instructions = instructions
        if self._error:
            raise self._error
        return self._result


class StubLLM:
    def __init__(self, text="transcribed", error=None):
        self._text = text
        self._error = error

    def transcribe(self, audio, filename="audio.webm"):
        if self._error:
            raise self._error
        return self._text


def a_result(**overrides):
    defaults = dict(
        query="q", summary="the answer", sources=("http://a.com",), recalled=(), tokens=1
    )
    defaults.update(overrides)
    return Research(**defaults)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(path=str(tmp_path / "chroma"), collection="testcol")


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    initialize(path)
    return path


@pytest.fixture
def chats(db):
    return ConversationStore(db)


@pytest.fixture
def projects(db):
    return ProjectStore(db)


# --- sidebar ----------------------------------------------------------


def test_sidebar_nests_conversations_under_their_project(projects, chats):
    project = projects.create("Career")
    chats.create("filed chat", project_id=project.id)

    data = api.handle_sidebar(projects, chats)

    assert data["projects"][0]["name"] == "Career"
    assert data["projects"][0]["conversations"][0]["title"] == "filed chat"


def test_sidebar_lists_unfiled_conversations_separately(projects, chats):
    chats.create("loose chat")

    data = api.handle_sidebar(projects, chats)

    assert [c["title"] for c in data["unfiled"]] == ["loose chat"]


def test_empty_project_still_appears(projects, chats):
    projects.create("Empty")

    data = api.handle_sidebar(projects, chats)

    assert data["projects"][0]["conversations"] == []


# --- asking -----------------------------------------------------------


def test_asking_without_a_conversation_creates_one(store, chats):
    researcher = StubResearcher(a_result())

    response = api.handle_ask(researcher, store, chats, "what is X")

    assert response["conversation_id"]
    assert chats.get(response["conversation_id"]).title == "what is X"


def test_asking_within_a_conversation_reuses_it(store, chats):
    existing = chats.create("existing")
    researcher = StubResearcher(a_result())

    response = api.handle_ask(researcher, store, chats, "follow up", existing.id)

    assert response["conversation_id"] == existing.id
    assert researcher.last_conversation_id == existing.id


def test_empty_message_is_rejected_without_creating_a_conversation(store, chats):
    api.handle_ask(StubResearcher(a_result()), store, chats, "   ")

    assert chats.all() == []


def test_asking_into_a_missing_conversation_errors(store, chats):
    response = api.handle_ask(
        StubResearcher(a_result()), store, chats, "hi", "nonexistent"
    )

    assert "error" in response


def test_a_failed_first_question_does_not_leave_an_empty_chat(store, chats):
    researcher = StubResearcher(error=ValueError("no sources"))

    response = api.handle_ask(researcher, store, chats, "what is X")

    assert response["error"] == "no sources"
    assert chats.all() == [], "an empty chat should not survive a failed first ask"


def test_a_failure_in_an_existing_chat_leaves_it_alone(store, chats):
    existing = chats.create("keep me")
    researcher = StubResearcher(error=ValueError("boom"))

    api.handle_ask(researcher, store, chats, "q", existing.id)

    assert chats.get(existing.id) is not None


# --- conversation entries --------------------------------------------


def test_opening_a_conversation_returns_its_entries(store, chats):
    chat = chats.create("t")
    store.add("q1", "a1", [], conversation_id=chat.id)

    data = api.handle_conversation_entries(store, chats, chat.id)

    assert [e["query"] for e in data["entries"]] == ["q1"]


def test_opening_a_conversation_clears_unread(store, chats):
    chat = chats.create("t")
    chats.set_unread(chat.id, True)

    api.handle_conversation_entries(store, chats, chat.id)

    assert chats.get(chat.id).unread is False


def test_the_open_response_reports_the_cleared_unread_state(store, chats):
    # Returning the pre-clear snapshot would tell the client a chat it
    # just opened is still unread.
    chat = chats.create("t")
    chats.set_unread(chat.id, True)

    data = api.handle_conversation_entries(store, chats, chat.id)

    assert data["conversation"]["unread"] is False


def test_opening_a_missing_conversation_errors(store, chats):
    assert "error" in api.handle_conversation_entries(store, chats, "nope")


# --- mutations --------------------------------------------------------


def test_renaming_through_the_handler(chats):
    chat = chats.create("old")

    api.handle_update_conversation(chats, chat.id, {"title": "new"})

    assert chats.get(chat.id).title == "new"


def test_pinning_through_the_handler(chats):
    chat = chats.create("t")

    api.handle_update_conversation(chats, chat.id, {"pinned": True})

    assert chats.get(chat.id).pinned is True


def test_marking_unread_through_the_handler(chats):
    chat = chats.create("t")

    api.handle_update_conversation(chats, chat.id, {"unread": True})

    assert chats.get(chat.id).unread is True


def test_moving_into_and_out_of_a_project(chats, projects):
    project = projects.create("Career")
    chat = chats.create("t")

    api.handle_update_conversation(chats, chat.id, {"project_id": project.id})
    assert chats.get(chat.id).project_id == project.id

    api.handle_update_conversation(chats, chat.id, {"project_id": None})
    assert chats.get(chat.id).project_id is None


def test_only_supplied_fields_are_changed(chats):
    chat = chats.create("original")
    chats.set_pinned(chat.id, True)

    api.handle_update_conversation(chats, chat.id, {"title": "renamed"})

    updated = chats.get(chat.id)
    assert updated.title == "renamed"
    assert updated.pinned is True, "an unsent field must not be reset"


def test_updating_a_missing_conversation_errors(chats):
    assert "error" in api.handle_update_conversation(chats, "nope", {"title": "x"})


def test_deleting_a_conversation_removes_it_and_its_entries(store, chats):
    chat = chats.create("t")
    store.add("q", "a", [], conversation_id=chat.id)

    response = api.handle_delete_conversation(store, chats, chat.id)

    assert response["entries_deleted"] == 1
    assert chats.get(chat.id) is None
    assert store.count() == 0


def test_deleting_a_missing_conversation_errors(store, chats):
    assert "error" in api.handle_delete_conversation(store, chats, "nope")


def test_deleting_a_project_keeps_its_chats(projects, chats):
    project = projects.create("Career")
    chat = chats.create("keep me", project_id=project.id)

    api.handle_delete_project(projects, project.id)

    assert chats.get(chat.id) is not None
    assert chats.get(chat.id).project_id is None


def test_creating_a_project_with_a_blank_name_errors(projects):
    assert "error" in api.handle_create_project(projects, "   ")


# --- project detail and highlights ------------------------------------


HL_JSON = '{"highlights": [{"headline": "Do the thing", "detail": "d", "source": "s"}]}'


class HighlightLLM:
    def __init__(self, text=HL_JSON, error=None):
        self._text = text
        self._error = error
        self.calls = 0

    def complete(self, system, user, max_tokens=800):
        self.calls += 1
        if self._error:
            raise self._error
        from mindtrail.llm import Completion

        return Completion(text=self._text, tokens=1, model="stub")


def test_project_detail_reports_its_chats_and_files(store, chats, projects):
    project = projects.create("Career")
    chat = chats.create("c", project_id=project.id)
    store.add("q", "a", [], conversation_id=chat.id)
    store.add("Document: cv.pdf", "text", [], kind="document", conversation_id=chat.id)

    data = api.handle_project_detail(
        store, chats, projects, HighlightLLM(), project.id
    )

    assert data["name"] == "Career"
    assert [c["title"] for c in data["conversations"]] == ["c"]
    assert [f["name"] for f in data["files"]] == ["cv.pdf"]


def test_highlights_are_generated_for_a_project_with_content(store, chats, projects):
    project = projects.create("Career")
    chat = chats.create("c", project_id=project.id)
    store.add("q", "a", [], conversation_id=chat.id)

    data = api.handle_project_detail(
        store, chats, projects, HighlightLLM(), project.id
    )

    assert [h["headline"] for h in data["highlights"]] == ["Do the thing"]


def test_unchanged_projects_reuse_cached_highlights(store, chats, projects):
    project = projects.create("Career")
    chat = chats.create("c", project_id=project.id)
    store.add("q", "a", [], conversation_id=chat.id)
    llm = HighlightLLM()

    api.handle_project_detail(store, chats, projects, llm, project.id)
    api.handle_project_detail(store, chats, projects, llm, project.id)

    assert llm.calls == 1, "opening an unchanged project must not cost a second call"


def test_new_activity_makes_highlights_regenerate(store, chats, projects):
    project = projects.create("Career")
    chat = chats.create("c", project_id=project.id)
    store.add("q1", "a", [], conversation_id=chat.id)
    llm = HighlightLLM()

    api.handle_project_detail(store, chats, projects, llm, project.id)
    store.add("q2", "a", [], conversation_id=chat.id)
    api.handle_project_detail(store, chats, projects, llm, project.id)

    assert llm.calls == 2


def test_refresh_forces_regeneration(store, chats, projects):
    project = projects.create("Career")
    chat = chats.create("c", project_id=project.id)
    store.add("q", "a", [], conversation_id=chat.id)
    llm = HighlightLLM()

    api.handle_project_detail(store, chats, projects, llm, project.id)
    api.handle_project_detail(store, chats, projects, llm, project.id, refresh=True)

    assert llm.calls == 2


def test_an_empty_project_generates_nothing(store, chats, projects):
    project = projects.create("Empty")
    llm = HighlightLLM()

    data = api.handle_project_detail(store, chats, projects, llm, project.id)

    assert data["highlights"] == []
    assert llm.calls == 0


def test_a_failed_refresh_keeps_the_previous_highlights(store, chats, projects):
    from mindtrail.llm import LLMError

    project = projects.create("Career")
    chat = chats.create("c", project_id=project.id)
    store.add("q", "a", [], conversation_id=chat.id)
    api.handle_project_detail(store, chats, projects, HighlightLLM(), project.id)

    data = api.handle_project_detail(
        store, chats, projects, HighlightLLM(error=LLMError("rate limited")),
        project.id, refresh=True,
    )

    assert [h["headline"] for h in data["highlights"]] == ["Do the thing"]
    assert "rate limited" in data["highlights_error"]


def test_project_detail_of_a_missing_project_errors(store, chats, projects):
    assert "error" in api.handle_project_detail(
        store, chats, projects, HighlightLLM(), "nope"
    )


def test_instructions_can_be_saved_and_read_back(store, chats, projects):
    project = projects.create("Career")

    api.handle_update_project(projects, project.id, {"instructions": "no AI refs"})

    data = api.handle_project_detail(
        store, chats, projects, HighlightLLM(), project.id
    )
    assert data["instructions"] == "no AI refs"


def test_updating_instructions_does_not_clear_the_name(projects):
    project = projects.create("Career")

    api.handle_update_project(projects, project.id, {"instructions": "x"})

    assert projects.get(project.id).name == "Career"


# --- instructions reach the researcher --------------------------------


def test_a_chat_in_a_project_passes_its_instructions_to_research(store, chats, projects):
    class CapturingResearcher:
        def __init__(self):
            self.instructions = None

        def research_and_store(self, query, conversation_id="", instructions=""):
            self.instructions = instructions
            return a_result()

    project = projects.create("Career")
    projects.set_instructions(project.id, "never cite AI")
    chat = chats.create("c", project_id=project.id)
    researcher = CapturingResearcher()

    api.handle_ask(researcher, store, chats, "q", chat.id, None, projects)

    assert researcher.instructions == "never cite AI"


def test_a_chat_outside_a_project_gets_no_instructions(store, chats, projects):
    class CapturingResearcher:
        def __init__(self):
            self.instructions = None

        def research_and_store(self, query, conversation_id="", instructions=""):
            self.instructions = instructions
            return a_result()

    chat = chats.create("loose")
    researcher = CapturingResearcher()

    api.handle_ask(researcher, store, chats, "q", chat.id, None, projects)

    assert researcher.instructions == ""


# --- dictation and upload --------------------------------------------


def test_transcription_returns_text():
    assert api.handle_transcribe(StubLLM("hello there"), b"audio")["text"] == "hello there"


def test_transcription_failure_is_surfaced():
    from mindtrail.llm import LLMError

    response = api.handle_transcribe(StubLLM(error=LLMError("no audio")), b"")

    assert "error" in response


def test_upload_rejects_non_pdf(store, chats):
    response = api.handle_upload(store, chats, StubLLM(), "notes.txt", b"data")

    assert "error" in response


def test_upload_rejects_empty_body(store, chats):
    assert "error" in api.handle_upload(store, chats, StubLLM(), "a.pdf", b"")


def test_upload_of_an_unparseable_pdf_errors(store, chats):
    response = api.handle_upload(store, chats, StubLLM(), "a.pdf", b"not really a pdf")

    assert "error" in response


# --- ui ---------------------------------------------------------------


def test_chat_html_references_every_endpoint_it_uses():
    for endpoint in [
        "/api/sidebar",
        "/api/ask",
        "/api/projects",
        "/api/conversations/",
        "/api/upload",
        "/api/transcribe",
    ]:
        assert endpoint in CHAT_HTML


def test_no_native_dialogs_are_used():
    # window.prompt/confirm/alert render in the OS light theme regardless
    # of the page, which breaks the dark UI. Everything goes through the
    # in-page modal instead.
    for call in ["prompt(", "confirm(", "alert("]:
        assert call not in CHAT_HTML, f"native {call} would render an unstyled dialog"


def test_the_in_page_modal_exists():
    assert 'id="overlay"' in CHAT_HTML
    assert ".modal {" in CHAT_HTML, "the modal needs styling to replace native dialogs"
    assert "function modal(" in CHAT_HTML


def test_sidebar_can_be_collapsed_and_navigated():
    for element in ["toggle-sidebar", "nav-back", "nav-fwd"]:
        assert element in CHAT_HTML
    assert "#sidebar.collapsed" in CHAT_HTML
