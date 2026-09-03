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
from mindtrail.advice.profile_draft import draft_profile
from mindtrail.advice.roadmap_chat import chat_about_roadmap
from mindtrail.advice.roadmap_gen import generate_roadmap
from mindtrail.ingest.documents import DocumentError, extract_pdf_text
from mindtrail.ingest.researcher import Researcher
from mindtrail.llm import LLMClient, LLMError
from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore, title_from_question
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
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


NEXT_UP_STATUS = "accepted"
DASHBOARD_ITEMS_PER_PROJECT = 2
DASHBOARD_RECENT_LIMIT = 8


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

    next_up = []
    for project in all_projects:
        roadmap = roadmaps.for_project(project.id)
        if roadmap is None:
            continue
        accepted = [n for n in nodes.for_roadmap(roadmap.id) if n.status == NEXT_UP_STATUS]
        # x position roughly tracks dependency order from the generated
        # layout, so it doubles as "what's next" without a due-date field.
        accepted.sort(key=lambda n: n.x)
        for n in accepted[:DASHBOARD_ITEMS_PER_PROJECT]:
            next_up.append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "node_id": n.id,
                    "title": n.title,
                    "note": n.note,
                }
            )

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

    return {"highlights": highlights, "next_up": next_up, "recent": recent}


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
    )
    return _node_json(node)


def handle_delete_node(nodes: RoadmapNodeStore, node_id: str) -> dict:
    try:
        nodes.delete(node_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}
