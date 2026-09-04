"""Request handlers for the chat server.

Pure functions over the stores, with no reference to sockets or HTTP
plumbing, so every branch is testable without standing a server up.
"""

from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from mindtrail.advice.highlights import (
    generate_highlights,
    highlights_from_json,
    highlights_to_json,
)
from mindtrail.advice.profile_chat import chat_about_profile
from mindtrail.advice.profile_draft import draft_profile
from mindtrail.advice.project_chat import chat_about_project
from mindtrail.advice.roadmap_chat import chat_about_roadmap
from mindtrail.advice.roadmap_gen import generate_roadmap
from mindtrail.ingest.documents import DocumentError, extract_pdf_text
from mindtrail.ingest.researcher import Researcher
from mindtrail.llm import LLMClient, LLMError
from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore, title_from_question
from mindtrail.organize.export import default_export_dir, export_to_directory
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmap_templates import TEMPLATES, get_template
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.organize.trash import DeletedConversation, NodeTrash, Trash


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


NEXT_UP_STATUS = "accepted"
DASHBOARD_ITEMS_PER_PROJECT = 2
DASHBOARD_RECENT_LIMIT = 8

# done and rejected nodes are no longer decisions waiting to happen, so
# they are not agenda items even if they carry a due date.
AGENDA_STATUSES = ("accepted", "proposed")
# "This week" is a 7-day rolling window from today, not a calendar week -
# a Friday shouldn't see two days of "this week" and call everything
# past Sunday "later". A node due exactly 7 days out still reads as
# "this week"; 8 days out is "later".
AGENDA_WEEK_DAYS = 7


def _parse_due_date(raw: str) -> date | None:
    """due_date is a free-form string field in storage, not a real SQL
    date column - malformed or half-entered values are skipped rather
    than crashing the whole dashboard."""
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _agenda_bucket(due: date, today: date) -> str:
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    if due <= today + timedelta(days=AGENDA_WEEK_DAYS):
        return "this_week"
    return "later"


def handle_dashboard(
    projects: ProjectStore,
    chats: ConversationStore,
    roadmaps: RoadmapStore,
    nodes: RoadmapNodeStore,
) -> dict:
    """The landing overview: cached highlights, accepted-but-not-done
    roadmap steps, and recent activity, across every project.

    Everything here is already stored or cached - no LLM call is ever
    made, so opening the dashboard costs nothing and is never stale in
    a way that needs a spinner.
    """
    all_projects = projects.all()
    project_names = {p.id: p.name for p in all_projects}

    highlights = []
    for project in all_projects:
        for h in highlights_from_json(project.advice)[:DASHBOARD_ITEMS_PER_PROJECT]:
            highlights.append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "headline": h.headline,
                    "priority": h.priority,
                }
            )

    # "Today" is read from the server's local clock, not UTC, and that
    # choice is made once here rather than per-node. mindtrail's chat
    # server is a single local process the user runs on their own
    # machine (see PLAN.md) - there is no separate browser timezone to
    # reconcile against, the server's local date already *is* the user's.
    # due_date is stored as a bare YYYY-MM-DD with no offset, so comparing
    # it against a UTC "today" would misclassify anything due near
    # midnight local time as overdue (or not) for roughly half the day,
    # depending on which side of UTC the user sits on - exactly the
    # trust-eroding bug this task calls out.
    today = datetime.now().date()

    next_up = []
    agenda: dict[str, list[dict]] = {
        "overdue": [], "today": [], "this_week": [], "later": []
    }
    for project in all_projects:
        roadmap = roadmaps.for_project(project.id)
        if roadmap is None:
            continue
        all_nodes = nodes.for_roadmap(roadmap.id)
        by_id = {n.id: n for n in all_nodes}
        accepted = [n for n in all_nodes if n.status == NEXT_UP_STATUS]

        def is_unblocked(n) -> bool:
            return all(
                by_id.get(dep_id) is not None and by_id[dep_id].status == "done"
                for dep_id in n.depends_on
            )

        # Genuinely unblocked steps (every dependency already done) lead.
        # Within that, a real due date beats the x-position guess - sorts
        # soonest first, with undated steps pushed to the end of their
        # bucket rather than competing on a coordinate that was never
        # meant to encode urgency. A step still waiting on a dependency
        # sorts after rather than being hidden, so a project with a real
        # plan doesn't look empty just because its next actionable step
        # hasn't been reached yet.
        accepted.sort(key=lambda n: (not is_unblocked(n), n.due_date or "9999-99-99", n.x))
        for n in accepted[:DASHBOARD_ITEMS_PER_PROJECT]:
            next_up.append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "node_id": n.id,
                    "title": n.title,
                    "note": n.note,
                    "due_date": n.due_date,
                    "unblocked": is_unblocked(n),
                }
            )

        # The agenda card, unlike next_up, is not capped per project and
        # is not limited to accepted nodes - a proposed step with a due
        # date is still something the user committed a date to, just not
        # yet decided to act on, and done/rejected nodes are no longer
        # agenda items at all.
        for n in all_nodes:
            if n.status not in AGENDA_STATUSES or not n.due_date:
                continue
            due = _parse_due_date(n.due_date)
            if due is None:
                continue
            agenda[_agenda_bucket(due, today)].append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "node_id": n.id,
                    "title": n.title,
                    "due_date": n.due_date,
                }
            )

    for bucket in agenda.values():
        bucket.sort(key=lambda item: (item["due_date"], item["project_name"]))

    recent = [
        {
            "id": c.id,
            "title": c.title,
            "project_id": c.project_id,
            "project_name": project_names.get(c.project_id) if c.project_id else None,
            "updated_at": c.updated_at,
        }
        for c in chats.all()[:DASHBOARD_RECENT_LIMIT]
    ]

    return {
        "highlights": highlights, "next_up": next_up, "recent": recent, "agenda": agenda
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
    profile: ProfileStore | None = None,
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
            profile_text = profile.get().content if profile is not None else ""
            generated = generate_highlights(
                llm, usable, project.instructions, profile_text
            )
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
        # Recomputed against the (possibly just-refreshed) project, not
        # the `stale` captured before generation ran - otherwise a
        # successful refresh still reported itself as stale.
        "highlights_stale": len(usable) != project.advice_basis_count and bool(usable),
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


def handle_project_chat(
    projects: ProjectStore,
    llm: LLMClient,
    profile: ProfileStore,
    project_id: str,
    message: str,
    history: list[dict],
) -> dict:
    """A conversational turn about one project. Never writes to it - the
    model can only propose a rename and/or instructions change, which the
    caller applies through the existing update-project endpoint once the
    user accepts.
    """
    project = projects.get(project_id)
    if project is None:
        return {"error": "no such project"}

    try:
        result = chat_about_project(
            llm, project.name, project.instructions,
            profile.get().content, history, message,
        )
    except (LLMError, ValueError) as exc:
        return {"error": str(exc)}

    return {
        "reply": result.reply,
        "actions": [
            {"type": a.type, "name": a.name, "instructions": a.instructions, "label": a.label}
            for a in result.actions
        ],
    }


def handle_delete_project(projects: ProjectStore, project_id: str) -> dict:
    try:
        projects.delete(project_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


SEARCH_DEFAULT_K = 10


def handle_search(
    store: MemoryStore, chats: ConversationStore, projects: ProjectStore, query: str
) -> dict:
    """Semantic search over everything stored - the app's core retrieval,
    previously reachable only from a follow-up question inside a chat,
    never directly from the browser.
    """
    query = query.strip()
    if not query:
        return {"results": []}

    results = []
    for entry in store.search(query, k=SEARCH_DEFAULT_K):
        conversation = chats.get(entry.conversation_id) if entry.conversation_id else None
        project_name = None
        if conversation and conversation.project_id:
            project = projects.get(conversation.project_id)
            project_name = project.name if project else None
        results.append(
            {
                "id": entry.id,
                "query": entry.query,
                "summary": entry.summary,
                "kind": entry.kind,
                "topic": entry.topic,
                "created_at": entry.created_at,
                "conversation_id": entry.conversation_id,
                "conversation_title": conversation.title if conversation else None,
                "project_name": project_name,
            }
        )
    return {"results": results}


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
                "id": e.id,
                "query": e.query,
                "summary": e.summary,
                "created_at": e.created_at,
                "kind": e.kind,
                "sources": list(e.sources),
                "recalled": _resolve_recalled(store, e.recalled_ids),
            }
            for e in store.by_conversation(conversation_id)
        ],
    }


def _resolve_recalled(store: MemoryStore, recalled_ids: tuple[str, ...]) -> list[dict]:
    """Turns stored recalled_ids into something a client can render and
    link into - a query to show and a conversation to open. A recalled
    entry whose conversation was since deleted is skipped rather than
    shown as a dead link.
    """
    resolved = []
    for entry_id in recalled_ids:
        recalled = store.get(entry_id)
        if recalled is None or not recalled.conversation_id:
            continue
        resolved.append(
            {
                "id": recalled.id,
                "query": recalled.query,
                "conversation_id": recalled.conversation_id,
            }
        )
    return resolved


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


def _entry_json(entry) -> dict:
    return {
        "id": entry.id,
        "query": entry.query,
        "summary": entry.summary,
        "kind": entry.kind,
        "topic": entry.topic,
        "created_at": entry.created_at,
        "conversation_id": entry.conversation_id,
    }


def handle_update_entry(store: MemoryStore, entry_id: str, body: dict) -> dict:
    """Edit a single entry's text. Applies whichever of query/summary is
    present, same shape as handle_update_conversation, so the client can
    send just the field that changed.

    Goes through MemoryStore.update_entry, which re-embeds - this is the
    fix for G3's whole trap: a plain text swap without re-embedding
    would leave recall silently matching the old wording.
    """
    try:
        updated = store.update_entry(
            entry_id,
            summary=str(body["summary"]) if "summary" in body else None,
            query=str(body["query"]) if "query" in body else None,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"error": "no such entry"} if updated is None else _entry_json(updated)


def handle_delete_entry(store: MemoryStore, entry_id: str) -> dict:
    """Delete a single entry. Unlike handle_delete_conversation this has
    no undo - a bad entry should just be gone, and there is no
    conversation-shaped container left to hold a copy in."""
    removed = store.delete_entry(entry_id)
    return {"ok": True} if removed else {"error": "no such entry"}


def handle_ask(
    researcher: Researcher,
    store: MemoryStore,
    chats: ConversationStore,
    message: str,
    conversation_id: str = "",
    project_id: str | None = None,
    projects: ProjectStore | None = None,
    profile: ProfileStore | None = None,
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

    profile_text = profile.get().content if profile is not None else ""

    try:
        result = researcher.research_and_store(
            message,
            conversation_id=conversation_id,
            instructions=instructions,
            profile=profile_text,
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
        "recalled": [
            {"id": e.id, "query": e.query, "conversation_id": e.conversation_id}
            for e in result.recalled
        ],
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


def handle_add_note(
    store: MemoryStore,
    chats: ConversationStore,
    text: str,
    conversation_id: str = "",
    topic_extractor=None,
) -> dict:
    """Store a manual note the same way research and documents are -
    topic-labeled, searchable, and attached to a conversation. The CLI
    version of this stores notes with no conversation_id at all, which
    is why they've been invisible in the browser; this always attaches
    one, matching how handle_upload already treats a document.
    """
    text = text.strip()
    if not text:
        return {"error": "note must not be empty"}

    headline = text.splitlines()[0][:80]

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
            pass  # labeling is a nicety; the note still gets stored

    store.add(
        headline, text, [], topic=topic, key_facts=facts,
        kind="note", conversation_id=conversation_id,
    )
    chats.touch(conversation_id)

    return {"ok": True, "conversation_id": conversation_id}


# --- profile ------------------------------------------------------------


def handle_get_profile(profile: ProfileStore) -> dict:
    p = profile.get()
    return {"content": p.content, "updated_at": p.updated_at, "is_empty": p.is_empty}


def handle_save_profile(profile: ProfileStore, content: str) -> dict:
    saved = profile.save(content)
    return {"content": saved.content, "updated_at": saved.updated_at}


def handle_draft_profile(store: MemoryStore, llm: LLMClient) -> dict:
    try:
        draft = draft_profile(llm, store.all())
    except (LLMError, ValueError) as exc:
        return {"error": str(exc)}
    return {"draft": draft}


def handle_profile_chat(
    profile: ProfileStore, llm: LLMClient, message: str, history: list[dict]
) -> dict:
    """A conversational turn about the profile. Never writes to it - the
    model can only propose a full replacement, which the caller saves
    through the existing save-profile endpoint once the user accepts.
    """
    try:
        result = chat_about_profile(llm, profile.get().content, history, message)
    except (LLMError, ValueError) as exc:
        return {"error": str(exc)}

    return {
        "reply": result.reply,
        "actions": [
            {"type": a.type, "content": a.content, "label": a.label} for a in result.actions
        ],
    }


# --- roadmaps -------------------------------------------------------------


def _node_json(node) -> dict:
    return {
        "id": node.id,
        "title": node.title,
        "detail": node.detail,
        "status": node.status,
        "note": node.note,
        "x": node.x,
        "y": node.y,
        "depends_on": list(node.depends_on),
        "due_date": node.due_date,
    }


def handle_get_roadmap(
    roadmaps: RoadmapStore, nodes: RoadmapNodeStore, project_id: str
) -> dict:
    """The project's roadmap, or an empty shell if none exists yet -
    the canvas can render either without a special case in the client."""
    roadmap = roadmaps.for_project(project_id)
    if roadmap is None:
        return {"roadmap": None, "nodes": []}
    return {
        "roadmap": {"id": roadmap.id, "goal": roadmap.goal},
        "nodes": [_node_json(n) for n in nodes.for_roadmap(roadmap.id)],
    }


# A card is 220px wide and, with a title, a couple lines of detail, and
# sometimes a note, commonly renders 160-220px tall - measured against
# real generated content, not guessed. The old constants (260/130) gave
# a 40px horizontal gap and a row height *shorter* than a typical card,
# so neighbors routinely overlapped. These leave real breathing room on
# both axes.
LAYOUT_COLUMN_WIDTH = 320
LAYOUT_ROW_HEIGHT = 260


def _place_new_nodes(existing: list, proposed) -> list[tuple]:
    """A simple left-to-right, dependency-respecting grid.

    Good enough to start from; the user drags from here. A node's column
    is one past the furthest column of anything it depends on, so edges
    generally point rightward instead of crossing back over themselves.
    """
    by_title = {n.title: n for n in existing}
    columns: dict[str, int] = {n.title: int(n.x // LAYOUT_COLUMN_WIDTH) for n in existing}
    max_col = max(columns.values(), default=-1)
    placed = []

    for item in proposed:
        deps_cols = [columns[d] for d in item.depends_on if d in columns]
        col = (max(deps_cols) + 1) if deps_cols else 0
        row = sum(1 for c in columns.values() if c == col)
        columns[item.title] = col
        placed.append((item, col * LAYOUT_COLUMN_WIDTH, row * LAYOUT_ROW_HEIGHT))
        max_col = max(max_col, col)

    return placed


# Within a column, row order follows what's worth looking at first:
# accepted work in progress, then proposed suggestions still waiting on
# a decision, then what's already done, with rejected trailing at the
# bottom - so tidying doesn't just de-overlap, it puts what matters
# most near the top-left.
ROW_PRIORITY = {"accepted": 0, "proposed": 1, "done": 2, "rejected": 3}


def _grid_positions(all_nodes: list) -> dict[str, tuple[float, float]]:
    """Column = one past the deepest dependency's column, so edges point
    rightward. Row = priority order within that column (see ROW_PRIORITY).
    Shared by the tidy-up re-layout below - same spacing rule as fresh
    generation, just applied to every node instead of only new ones.
    """
    by_id = {n.id: n for n in all_nodes}
    column: dict[str, int] = {}

    def col_of(node_id: str, path: frozenset[str] = frozenset()) -> int:
        if node_id in column:
            return column[node_id]
        node = by_id.get(node_id)
        # A dependency cycle shouldn't happen, but a stray one must not
        # recurse forever - treat it as a root instead of hanging.
        if node is None or not node.depends_on or node_id in path:
            column[node_id] = 0
            return 0
        deps = [col_of(d, path | {node_id}) for d in node.depends_on if d in by_id]
        column[node_id] = (max(deps) + 1) if deps else 0
        return column[node_id]

    for n in all_nodes:
        col_of(n.id)

    ordered = sorted(all_nodes, key=lambda n: (column[n.id], ROW_PRIORITY.get(n.status, 1)))

    row_counts: dict[int, int] = {}
    positions = {}
    for n in ordered:
        col = column[n.id]
        row = row_counts.get(col, 0)
        row_counts[col] = row + 1
        positions[n.id] = (col * LAYOUT_COLUMN_WIDTH, row * LAYOUT_ROW_HEIGHT)
    return positions


def handle_tidy_roadmap(nodes: RoadmapNodeStore, roadmap_id: str) -> dict:
    """Re-run the grid layout over every node in the roadmap, ignoring
    current positions.

    For a roadmap dragged into a tangle, or one generated before the
    spacing was fixed, this is the reset button - accepted, done, and
    rejected nodes get re-laid-out too, since their *positions* aren't
    a decision the way their status is.
    """
    all_nodes = nodes.for_roadmap(roadmap_id)
    positions = _grid_positions(all_nodes)
    for n in all_nodes:
        x, y = positions[n.id]
        nodes.move(n.id, x, y)
    return {"nodes": [_node_json(n) for n in nodes.for_roadmap(roadmap_id)]}


def handle_roadmap_chat(
    roadmaps: RoadmapStore,
    nodes: RoadmapNodeStore,
    llm: LLMClient,
    profile: ProfileStore,
    roadmap_id: str,
    message: str,
    history: list[dict],
) -> dict:
    """A conversational turn about one roadmap. Never writes to it - the
    model can only propose actions, which the caller applies (or doesn't)
    through the existing node endpoints once the user accepts each one.
    """
    roadmap = roadmaps.get(roadmap_id)
    if roadmap is None:
        return {"error": "no such roadmap"}

    current_nodes = nodes.for_roadmap(roadmap_id)
    try:
        result = chat_about_roadmap(
            llm, roadmap.goal, current_nodes, profile.get().content, history, message
        )
    except (LLMError, ValueError) as exc:
        return {"error": str(exc)}

    return {
        "reply": result.reply,
        "actions": [
            {
                "type": a.type,
                "node_id": a.node_id,
                "title": a.title,
                "detail": a.detail,
                "status": a.status,
                "note": a.note,
                "label": a.label,
            }
            for a in result.actions
        ],
    }


def handle_generate_roadmap(
    store: MemoryStore,
    chats: ConversationStore,
    projects: ProjectStore,
    roadmaps: RoadmapStore,
    nodes: RoadmapNodeStore,
    llm: LLMClient,
    profile: ProfileStore,
    project_id: str,
    goal: str = "",
) -> dict:
    """Create or extend a project's roadmap toward a goal.

    Decided nodes (accepted/done/rejected) and their notes are preserved
    and shown to the model as context; only proposed nodes are replaced,
    so a regeneration builds on what the user already decided.
    """
    project = projects.get(project_id)
    if project is None:
        return {"error": "no such project"}

    roadmap = roadmaps.for_project(project_id)
    if roadmap is None:
        if not goal.strip():
            return {"error": "a goal is required to start a roadmap"}
        roadmap = roadmaps.create(goal, project_id=project_id)

    existing = nodes.for_roadmap(roadmap.id)
    decided = [n for n in existing if n.status != "proposed"]
    still_proposed = [n for n in existing if n.status == "proposed"]

    try:
        proposal = generate_roadmap(
            llm,
            roadmap.goal,
            profile=profile.get().content,
            project_entries=project_entries(store, chats, project_id),
            existing_nodes=decided,
        )
    except (LLMError, ValueError) as exc:
        return {"error": str(exc)}

    for stale in still_proposed:
        nodes.delete(stale.id)

    title_to_id = {n.title: n.id for n in decided}
    placed = _place_new_nodes(decided, proposal)
    for item, x, y in placed:
        created = nodes.add(
            roadmap.id, item.title, item.detail, status="proposed", x=x, y=y
        )
        title_to_id[item.title] = created.id

    for item, _, _ in placed:
        deps = [title_to_id[d] for d in item.depends_on if d in title_to_id]
        if deps:
            nodes.set_depends_on(title_to_id[item.title], deps)

    return handle_get_roadmap(roadmaps, nodes, project_id)


def handle_list_templates() -> dict:
    return {
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "step_count": len(t.steps),
            }
            for t in TEMPLATES
        ]
    }


def handle_apply_template(
    roadmaps: RoadmapStore,
    nodes: RoadmapNodeStore,
    projects: ProjectStore,
    project_id: str,
    template_id: str,
    goal: str = "",
) -> dict:
    """Instantiate a template's steps as proposed nodes on the project's
    roadmap.

    Unlike generation, this never deletes anything - applying a template
    twice is the user's choice, not a bug to prevent. Steps propose, they
    do not decide, so they land with status="proposed" and go through the
    same accept/reject flow as an LLM-generated step.
    """
    project = projects.get(project_id)
    if project is None:
        return {"error": "no such project"}

    template = get_template(template_id)
    if template is None:
        return {"error": "no such template"}

    roadmap = roadmaps.for_project(project_id)
    if roadmap is None:
        roadmap = roadmaps.create(goal.strip() or template.name, project_id=project_id)

    existing = nodes.for_roadmap(roadmap.id)
    placed = _place_new_nodes(existing, template.steps)

    title_to_id: dict[str, str] = {}
    for item, x, y in placed:
        created = nodes.add(
            roadmap.id, item.title, item.detail, status="proposed", x=x, y=y
        )
        title_to_id[item.title] = created.id

    for item, _, _ in placed:
        deps = [title_to_id[d] for d in item.depends_on if d in title_to_id]
        if deps:
            nodes.set_depends_on(title_to_id[item.title], deps)

    return handle_get_roadmap(roadmaps, nodes, project_id)


def _creates_cycle(node_id: str, depends_on: list[str], all_nodes: list) -> bool:
    """True if setting `node_id`'s depends_on to `depends_on` would let a
    dependency chain lead back to `node_id`.

    Deliberately separate from `_grid_positions`'s cycle handling: that one
    is cycle *tolerance* fused to column assignment (it stops recursion so
    layout doesn't hang, but never reports whether a cycle exists). This is
    a plain reachability check with no other job.
    """
    adjacency = {n.id: list(n.depends_on) for n in all_nodes}
    adjacency[node_id] = list(depends_on)

    stack: set[str] = set()
    visited: set[str] = set()

    def visit(current: str) -> bool:
        if current in stack:
            return True
        if current in visited:
            return False
        visited.add(current)
        stack.add(current)
        for dep in adjacency.get(current, []):
            if visit(dep):
                return True
        stack.discard(current)
        return False

    return visit(node_id)


def _validate_depends_on(nodes: RoadmapNodeStore, node_id: str, depends_on) -> list[str]:
    """The only place `depends_on` is checked before it reaches the
    database - `RoadmapNodeStore.set_depends_on` itself is a bare
    ",".join(...) with no validation at all, so this is the whole guard.

    Rejects a non-list (the wire format is pinned to a list of ids, not a
    comma-joined string), self-links, duplicates, ids that don't belong to
    a node in the same roadmap (which also covers unknown ids and
    cross-roadmap ids in one check), and anything that would create a
    dependency cycle.
    """
    if not isinstance(depends_on, list) or not all(isinstance(d, str) for d in depends_on):
        raise ValueError("depends_on must be a list of node ids")
    if node_id in depends_on:
        raise ValueError("a node cannot depend on itself")
    if len(set(depends_on)) != len(depends_on):
        raise ValueError("depends_on contains duplicate ids")

    target = nodes.get(node_id)
    if target is None:
        raise ValueError("no such node")

    all_nodes = nodes.for_roadmap(target.roadmap_id)
    by_id = {n.id: n for n in all_nodes}
    unknown = [d for d in depends_on if d not in by_id]
    if unknown:
        raise ValueError(f"unknown or cross-roadmap node id: {unknown[0]}")

    if _creates_cycle(node_id, depends_on, all_nodes):
        raise ValueError("that would create a dependency cycle")

    return depends_on


def handle_update_node(nodes: RoadmapNodeStore, node_id: str, body: dict) -> dict:
    try:
        if "status" in body:
            nodes.set_status(node_id, str(body["status"]))
        if "note" in body:
            nodes.set_note(node_id, str(body["note"]))
        if "x" in body and "y" in body:
            nodes.move(node_id, float(body["x"]), float(body["y"]))
        if "title" in body:
            nodes.rename(node_id, str(body["title"]), str(body.get("detail", "")))
        if "due_date" in body:
            nodes.set_due_date(node_id, str(body["due_date"]))
        if "depends_on" in body:
            nodes.set_depends_on(node_id, _validate_depends_on(nodes, node_id, body["depends_on"]))
    except ValueError as exc:
        return {"error": str(exc)}
    updated = nodes.get(node_id)
    return {"error": "no such node"} if updated is None else _node_json(updated)


def handle_add_node(nodes: RoadmapNodeStore, roadmap_id: str, body: dict) -> dict:
    title = str(body.get("title", ""))
    if not title.strip():
        return {"error": "node title must not be empty"}
    node = nodes.add(
        roadmap_id,
        title,
        str(body.get("detail", "")),
        status="accepted",  # a node the user adds by hand is already decided
        x=float(body.get("x", 0)),
        y=float(body.get("y", 0)),
        due_date=str(body.get("due_date", "")),
    )
    return _node_json(node)


def handle_delete_node(
    nodes: RoadmapNodeStore, node_id: str, node_trash: NodeTrash | None = None
) -> dict:
    """Delete a node, holding a copy for undo - mirrors
    `handle_delete_conversation`'s shape exactly."""
    node = nodes.get(node_id)
    if node is None:
        return {"error": f"no such node: {node_id}"}

    if node_trash is not None:
        node_trash.put(node)

    nodes.delete(node_id)
    return {"ok": True, "undoable": node_trash is not None}


def handle_undo_delete_node(
    nodes: RoadmapNodeStore, node_trash: NodeTrash, node_id: str
) -> dict:
    """Restore a roadmap node deleted within the undo window.

    Restored under its original id - other nodes' `depends_on` still
    point at that id, and a fresh one would leave those edges dangling.
    """
    held = node_trash.take(node_id)
    if held is None:
        return {"error": "nothing left to undo"}

    nodes.restore(held)
    return {"ok": True, "node": _node_json(held)}


# --- export -----------------------------------------------------------


def handle_export(
    store: MemoryStore,
    chats: ConversationStore,
    projects: ProjectStore,
    roadmaps: RoadmapStore,
    nodes: RoadmapNodeStore,
    profile: ProfileStore,
    out: str = "",
    project_id: str | None = None,
) -> dict:
    target = out.strip() or default_export_dir()
    try:
        count = export_to_directory(
            store, chats, projects, roadmaps, nodes, profile, target, project_id
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"path": str(Path(target).resolve()), "files": count}
