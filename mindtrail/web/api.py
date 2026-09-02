"""Request handlers for the chat server.

Pure functions over the stores, with no reference to sockets or HTTP
plumbing, so every branch is testable without standing a server up.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from mindtrail.advice.highlights import (
    generate_highlights,
    highlights_from_json,
    highlights_to_json,
)
from mindtrail.ingest.documents import DocumentError, extract_pdf_text
from mindtrail.ingest.researcher import Researcher
from mindtrail.llm import LLMClient, LLMError
from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore, title_from_question
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.trash import DeletedConversation, Trash


def _conversation_json(conversation) -> dict:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "project_id": conversation.project_id,
        "pinned": conversation.pinned,
        "unread": conversation.unread,
        "updated_at": conversation.updated_at,
    }


def handle_sidebar(projects: ProjectStore, chats: ConversationStore) -> dict:
    """Everything the sidebar needs in one call.

    One round trip rather than one per project keeps the frontend from
    fanning out requests every time a chat is renamed or moved.
    """
    return {
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "conversations": [
                    _conversation_json(c) for c in chats.in_project(p.id)
                ],
            }
            for p in projects.all()
        ],
        "unfiled": [_conversation_json(c) for c in chats.in_project(None)],
    }


def _friendly_highlight_error(exc: Exception) -> str:
    """A short reason, never the model's raw output.

    Parse failures carry the offending text, which for a truncated
    response is a wall of half-finished JSON.
    """
    text = str(exc)
    if isinstance(exc, LLMError):
        return "rate limited" if "rate limited" in text else "the model was unavailable"
    if "no JSON" in text or "usable" in text:
        return "the suggestions came back malformed"
    return "suggestions could not be generated"


def project_entries(
    store: MemoryStore, chats: ConversationStore, project_id: str
) -> list:
    """Every entry across every conversation filed under a project."""
    entries = []
    for conversation in chats.in_project(project_id):
        entries.extend(store.by_conversation(conversation.id))
    return entries


def handle_project_detail(
    store: MemoryStore,
    chats: ConversationStore,
    projects: ProjectStore,
    llm: LLMClient,
    project_id: str,
    refresh: bool = False,
    allow_generate: bool = True,
) -> dict:
    """A project's chats, files, instructions, and next-step highlights.

    Highlights are cached with a count of what they were generated from,
    so they regenerate only when the project has actually moved on -
    otherwise opening a project would cost an LLM call every time.
    """
    project = projects.get(project_id)
    if project is None:
        return {"error": "no such project"}

    entries = project_entries(store, chats, project_id)
    usable = [e for e in entries if e.kind != "advice"]
    stale = len(usable) != project.advice_basis_count

    highlights = highlights_from_json(project.advice)
    error = ""
    # allow_generate is false when the view is being refreshed as a side
    # effect of something else (a move, a rename), where a multi-second
    # regeneration would make an unrelated action feel broken.
    if allow_generate and usable and (refresh or stale or not highlights):
        try:
            generated = generate_highlights(llm, usable, project.instructions)
            projects.save_advice(project_id, highlights_to_json(generated), len(usable))
            project = projects.get(project_id) or project
            highlights = generated
        except (LLMError, ValueError) as exc:
            # Keep showing the previous highlights rather than blanking
            # the panel because a refresh failed. The underlying message
            # can be a truncated JSON dump, which is useless to a reader,
            # so only a short reason is surfaced.
            error = _friendly_highlight_error(exc)

    conversations = chats.in_project(project_id)
    return {
        "id": project.id,
        "name": project.name,
        "instructions": project.instructions,
        "conversations": [_conversation_json(c) for c in conversations],
        "files": [
            {"name": e.query.replace("Document: ", ""), "conversation_id": e.conversation_id}
            for e in entries
            if e.kind == "document"
        ],
        "highlights": [
            {
                "headline": h.headline,
                "detail": h.detail,
                "source": h.source,
                "priority": h.priority,
            }
            for h in highlights
        ],
        "highlights_generated_at": project.advice_generated_at,
        "highlights_error": error,
        "highlights_stale": stale and bool(usable),
        "entry_count": len(usable),
    }


def handle_create_project(projects: ProjectStore, name: str) -> dict:
    try:
        project = projects.create(name)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"id": project.id, "name": project.name}


def handle_update_project(projects: ProjectStore, project_id: str, body: dict) -> dict:
    """Rename and/or set instructions; only supplied fields are applied."""
    try:
        if "name" in body:
            projects.rename(project_id, str(body["name"]))
        if "instructions" in body:
            projects.set_instructions(project_id, str(body["instructions"]))
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


def handle_delete_project(projects: ProjectStore, project_id: str) -> dict:
    try:
        projects.delete(project_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


def handle_conversation_entries(
    store: MemoryStore, chats: ConversationStore, conversation_id: str
) -> dict:
    """A chat's messages. Opening it clears its unread flag."""
    conversation = chats.get(conversation_id)
    if conversation is None:
        return {"error": "no such conversation"}

    if conversation.unread:
        chats.set_unread(conversation_id, False)
        # Re-read rather than returning the pre-clear snapshot, which
        # would report unread: true for a chat that was just opened.
        conversation = chats.get(conversation_id) or conversation

    return {
        "conversation": _conversation_json(conversation),
        "entries": [
            {
                "query": e.query,
                "summary": e.summary,
                "created_at": e.created_at,
                "kind": e.kind,
                "sources": list(e.sources),
            }
            for e in store.by_conversation(conversation_id)
        ],
    }


def handle_update_conversation(
    chats: ConversationStore, conversation_id: str, body: dict
) -> dict:
    """Rename, move, pin, or mark unread. Fields are applied if present,
    so the frontend can send just the one that changed."""
    try:
        if "title" in body:
            chats.rename(conversation_id, str(body["title"]))
        if "project_id" in body:
            target = body["project_id"]
            chats.move(conversation_id, target or None)
        if "pinned" in body:
            chats.set_pinned(conversation_id, bool(body["pinned"]))
        if "unread" in body:
            chats.set_unread(conversation_id, bool(body["unread"]))
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


def handle_delete_conversation(
    store: MemoryStore,
    chats: ConversationStore,
    conversation_id: str,
    trash: Trash | None = None,
) -> dict:
    """Delete the chat and its entries, holding a copy for undo.

    Unlike deleting a project, this destroys content - the entries would
    otherwise be unreachable from any view. The copy in the trash is what
    makes the undo button in the UI honest.
    """
    conversation = chats.get(conversation_id)
    if conversation is None:
        return {"error": "no such conversation"}

    entries = store.by_conversation(conversation_id)
    if trash is not None:
        trash.put(
            DeletedConversation(
                conversation_id=conversation_id,
                title=conversation.title,
                project_id=conversation.project_id,
                pinned=conversation.pinned,
                unread=conversation.unread,
                entries=tuple(
                    (e.query, e.summary, list(e.sources), e.topic, list(e.key_facts), e.kind)
                    for e in entries
                ),
            )
        )

    removed = store.delete_conversation_entries(conversation_id)
    chats.delete(conversation_id)
    return {"ok": True, "entries_deleted": removed, "undoable": trash is not None}


def handle_undo_delete(
    store: MemoryStore, chats: ConversationStore, trash: Trash, conversation_id: str
) -> dict:
    """Restore a conversation deleted within the undo window."""
    held = trash.take(conversation_id)
    if held is None:
        return {"error": "nothing left to undo"}

    # A new conversation row is created rather than reusing the id, since
    # the original was deleted; the id only needs to be stable for the
    # client to reopen it.
    restored = chats.create(title=held.title, project_id=held.project_id)
    if held.pinned:
        chats.set_pinned(restored.id, True)
    if held.unread:
        chats.set_unread(restored.id, True)

    for query, summary, sources, topic, key_facts, kind in held.entries:
        store.add(
            query,
            summary,
            sources,
            topic=topic,
            key_facts=key_facts,
            kind=kind,
            conversation_id=restored.id,
        )

    return {"ok": True, "conversation_id": restored.id, "entries": len(held.entries)}


def handle_ask(
    researcher: Researcher,
    store: MemoryStore,
    chats: ConversationStore,
    message: str,
    conversation_id: str = "",
    project_id: str | None = None,
    projects: ProjectStore | None = None,
) -> dict:
    """Answer a question, creating a conversation if this is a new chat."""
    if not message.strip():
        return {"error": "message was empty"}

    created_conversation = False
    if not conversation_id:
        conversation = chats.create(
            title=title_from_question(message), project_id=project_id
        )
        conversation_id = conversation.id
        created_conversation = True
    else:
        conversation = chats.get(conversation_id)
        if conversation is None:
            return {"error": "no such conversation"}
        project_id = conversation.project_id

    # A chat inside a project inherits that project's instructions.
    instructions = ""
    if projects is not None and project_id:
        project = projects.get(project_id)
        instructions = project.instructions if project else ""

    try:
        result = researcher.research_and_store(
            message, conversation_id=conversation_id, instructions=instructions
        )
    except Exception as exc:  # noqa: BLE001 - surfaced in the chat UI
        if created_conversation:
            # Don't leave an empty chat behind when the very first
            # question fails.
            chats.delete(conversation_id)
        return {"error": str(exc)}

    chats.touch(conversation_id)

    stored = store.by_conversation(conversation_id)
    topic = stored[-1].topic if stored else ""

    return {
        "answer": result.summary,
        "sources": list(result.sources),
        "recalled": [e.query for e in result.recalled],
        "conversation_id": conversation_id,
        "topic": topic,
    }


def handle_transcribe(llm: LLMClient, audio: bytes) -> dict:
    try:
        return {"text": llm.transcribe(audio)}
    except LLMError as exc:
        return {"error": str(exc)}


def handle_upload(
    store: MemoryStore,
    chats: ConversationStore,
    llm: LLMClient,
    filename: str,
    data: bytes,
    conversation_id: str = "",
    topic_extractor=None,
) -> dict:
    """Store an uploaded PDF as a document entry in a conversation."""
    if not data:
        return {"error": "no file received"}
    if not filename.lower().endswith(".pdf"):
        return {"error": "only PDF files are supported"}

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(filename).name
        path.write_bytes(data)
        try:
            text = extract_pdf_text(path)
        except DocumentError as exc:
            return {"error": str(exc)}

    headline = f"Document: {Path(filename).name}"

    if not conversation_id:
        conversation_id = chats.create(title=headline).id
    elif chats.get(conversation_id) is None:
        return {"error": "no such conversation"}

    topic, facts = "", []
    if topic_extractor is not None:
        try:
            assignment = topic_extractor.extract(headline, text, store.topics())
            topic, facts = assignment.topic, list(assignment.key_facts)
        except (LLMError, ValueError):
            pass  # labeling is a nicety; the document still gets stored

    store.add(
        headline,
        text,
        [Path(filename).name],
        topic=topic,
        key_facts=facts,
        kind="document",
        conversation_id=conversation_id,
    )
    chats.touch(conversation_id)

    return {
        "ok": True,
        "conversation_id": conversation_id,
        "filename": Path(filename).name,
        "characters": len(text),
    }
