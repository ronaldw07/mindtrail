"""Import from a markdown export: round-trip fidelity, idempotency,
overwrite, and graceful handling of a hand-broken export."""

from __future__ import annotations

import re

import pytest

from mindtrail.memory.store import Entry, MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.export import NONE_YET, build_conversation_file, export_to_directory
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.restore import parse_conversation_file
from mindtrail.organize.restore_apply import import_from_directory
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(path=str(tmp_path / "chroma"), collection="testcol")


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def chats(db):
    return ConversationStore(db)


@pytest.fixture
def projects(db):
    return ProjectStore(db)


@pytest.fixture
def roadmaps(db):
    return RoadmapStore(db)


@pytest.fixture
def nodes(db):
    return RoadmapNodeStore(db)


@pytest.fixture
def profile(db):
    return ProfileStore(db)


def _fresh_stores(tmp_path, name):
    """A second, independent set of stores - the "empty database" side
    of a round trip."""
    db_path = str(tmp_path / f"{name}.db")
    initialize(db_path)
    store = MemoryStore(path=str(tmp_path / f"{name}_chroma"), collection=f"col_{name}")
    return (
        store,
        ConversationStore(db_path),
        ProjectStore(db_path),
        RoadmapStore(db_path),
        RoadmapNodeStore(db_path),
        ProfileStore(db_path),
    )


def _populate(store, chats, projects, roadmaps, nodes, profile):
    """A database that exercises every field the export/import pair
    needs to carry: projects, conversations with entries (sources,
    recalled ids), roadmaps with dependencies, due dates, notes,
    statuses, repeat_days, and linked entries, a profile, and notes."""
    project = projects.create("Career Change")
    projects.set_instructions(project.id, "Be blunt about weak spots.")

    conversation = chats.create("Job search", project_id=project.id)
    chats.set_pinned(conversation.id, True)
    chats.set_unread(conversation.id, True)
    first = store.add(
        "What is Kubernetes?", "A container orchestrator.", ["http://a"],
        conversation_id=conversation.id,
    )
    store.add(
        "How does it schedule pods?", "Via the scheduler.", ["http://b"],
        recalled_ids=[first.id], conversation_id=conversation.id,
    )

    chats.create("Unfiled chat")
    store.add("Doc note", "Body text of a standalone note.", [])

    roadmap = roadmaps.create("Get a job", project_id=project.id)
    base = nodes.add(
        roadmap.id, "Learn SQL", detail="Practice joins and window functions.",
        status="accepted", due_date="2026-01-01",
    )
    nodes.set_note(base.id, "Started this week")
    dependent = nodes.add(roadmap.id, "Apply", status="proposed", repeat_days=7)
    nodes.set_depends_on(dependent.id, [base.id])
    nodes.set_linked_entries(dependent.id, [first.id])
    nodes.add(roadmap.id, "Old attempt", status="rejected")
    nodes.add(roadmap.id, "Offer accepted", status="done")

    profile.save("CS student at UCI, targeting backend roles.")
    return project, roadmap


# --- round-trip fidelity ----------------------------------------------


def test_export_import_export_is_byte_identical(
    tmp_path, store, chats, projects, roadmaps, nodes, profile
):
    _populate(store, chats, projects, roadmaps, nodes, profile)

    first_dir = tmp_path / "export1"
    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(first_dir))

    store2, chats2, projects2, roadmaps2, nodes2, profile2 = _fresh_stores(tmp_path, "b")
    summary = import_from_directory(
        str(first_dir), store2, chats2, projects2, roadmaps2, nodes2, profile2
    )
    # Into a genuinely empty database - anything less than every record
    # created would mean the "identical" export below is trivially true
    # because nothing was actually restored. An import that skips
    # everything and calls the resulting no-op export a match proves
    # nothing about round-trip fidelity.
    assert summary.created > 0
    assert summary.skipped == 0
    assert summary.failed == 0

    second_dir = tmp_path / "export2"
    export_to_directory(store2, chats2, projects2, roadmaps2, nodes2, profile2, str(second_dir))

    first_files = {p.relative_to(first_dir): p.read_bytes() for p in first_dir.rglob("*") if p.is_file()}
    second_files = {p.relative_to(second_dir): p.read_bytes() for p in second_dir.rglob("*") if p.is_file()}
    assert first_files.keys() == second_files.keys()
    assert first_files == second_files


# --- idempotency and overwrite ------------------------------------------


def test_importing_twice_creates_no_duplicates(
    tmp_path, store, chats, projects, roadmaps, nodes, profile
):
    _populate(store, chats, projects, roadmaps, nodes, profile)
    out = tmp_path / "export"
    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(out))

    store2, chats2, projects2, roadmaps2, nodes2, profile2 = _fresh_stores(tmp_path, "b")
    first = import_from_directory(str(out), store2, chats2, projects2, roadmaps2, nodes2, profile2)
    second = import_from_directory(str(out), store2, chats2, projects2, roadmaps2, nodes2, profile2)

    assert first.created > 0
    assert second.created == 0
    assert second.skipped == first.created
    assert len(projects2.all()) == 1
    assert len(chats2.all()) == 2
    assert store2.count() == 3


def test_overwrite_replaces_existing_records(
    tmp_path, store, chats, projects, roadmaps, nodes, profile
):
    _populate(store, chats, projects, roadmaps, nodes, profile)
    out = tmp_path / "export"
    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(out))

    store2, chats2, projects2, roadmaps2, nodes2, profile2 = _fresh_stores(tmp_path, "b")
    import_from_directory(str(out), store2, chats2, projects2, roadmaps2, nodes2, profile2)

    summary = import_from_directory(
        str(out), store2, chats2, projects2, roadmaps2, nodes2, profile2, overwrite=True
    )

    assert summary.skipped == 0
    assert summary.failed == 0
    assert len(projects2.all()) == 1
    assert len(chats2.all()) == 2
    assert store2.count() == 3


# --- malformed input ------------------------------------------------------


def test_malformed_file_is_reported_and_the_rest_still_imports(
    tmp_path, store, chats, projects, roadmaps, nodes, profile
):
    _populate(store, chats, projects, roadmaps, nodes, profile)
    out = tmp_path / "export"
    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(out))

    broken = next((out / "conversations").glob("*.md"))
    broken.write_text("this is not a valid export file")

    store2, chats2, projects2, roadmaps2, nodes2, profile2 = _fresh_stores(tmp_path, "b")
    summary = import_from_directory(str(out), store2, chats2, projects2, roadmaps2, nodes2, profile2)

    assert summary.failed == 1
    assert any("could not parse conversation" in w for w in summary.warnings)
    # The rest of the tree - projects, roadmaps, the other conversation,
    # profile, notes - still made it in.
    assert len(projects2.all()) == 1
    assert len(chats2.all()) == 1


def test_unresolvable_dependency_title_is_dropped_with_a_warning(
    tmp_path, store, chats, projects, roadmaps, nodes, profile
):
    project = projects.create("Solo")
    roadmap = roadmaps.create("Goal", project_id=project.id)
    nodes.add(roadmap.id, "Only step", status="accepted")
    out = tmp_path / "export"
    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(out))

    roadmap_file = next((out / "projects").glob("*/roadmap.md"))
    text = roadmap_file.read_text()
    text = text.replace("- Depends on: none", "- Depends on: A step that never existed", 1)
    roadmap_file.write_text(text)

    store2, chats2, projects2, roadmaps2, nodes2, profile2 = _fresh_stores(tmp_path, "b")
    summary = import_from_directory(str(out), store2, chats2, projects2, roadmaps2, nodes2, profile2)

    assert summary.failed == 0
    assert any("not found, dropped" in w for w in summary.warnings)
    restored_roadmap = roadmaps2.for_project(
        next(p.id for p in projects2.all() if p.name == "Solo")
    )
    restored_node = nodes2.for_roadmap(restored_roadmap.id)[0]
    assert restored_node.depends_on == ()


# --- restored entries re-embed -------------------------------------------


def test_restored_entry_is_findable_by_semantic_search(
    tmp_path, store, chats, projects, roadmaps, nodes, profile
):
    conversation = chats.create("Research")
    store.add(
        "What is Kubernetes?",
        "Kubernetes is a container orchestration platform.",
        ["http://a"],
        conversation_id=conversation.id,
    )
    out = tmp_path / "export"
    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(out))

    store2, chats2, projects2, roadmaps2, nodes2, profile2 = _fresh_stores(tmp_path, "b")
    import_from_directory(str(out), store2, chats2, projects2, roadmaps2, nodes2, profile2)

    hits = store2.search("container orchestration platform", k=1)
    assert hits and hits[0].query == "What is Kubernetes?"


# --- summaries containing markdown that looks like this format's own
# syntax ---------------------------------------------------------------
#
# A research summary is LLM prose, not something mindtrail wrote itself,
# and it routinely contains headings, tables, and fenced code with `---`
# and `|` in it. Against a real database, `mindtrail import` mistook
# these for entry boundaries and frontmatter fences and failed to parse
# 3 of 20 files outright - this is the regression suite for that.

ADVERSARIAL_SUMMARIES = {
    "table": "A quick table.\n\n| A | B |\n|---|---|\n| 1 | 2 |",
    "fenced code with dashes and pipes": (
        "Some code:\n\n```text\n--- not frontmatter ---\nif a | b:\n    pass\n```"
    ),
    "yaml-looking line": 'Notes below.\n\nid: "not-real-frontmatter"\ntitle: "nope"',
    "embedded heading": "Intro line.\n\n## Looks Like Another Entry\n\nMore text after it.",
    "unicode": "Unicode check: caf\u00e9 \u2014 \u4f60\u597d \U0001f600 \u2705",
}


def test_entries_with_adversarial_markdown_survive_export_import_export(
    tmp_path, store, chats, projects, roadmaps, nodes, profile
):
    conversation = chats.create("Adversarial content")
    for label, summary in ADVERSARIAL_SUMMARIES.items():
        store.add(label, summary, [], conversation_id=conversation.id)

    first_dir = tmp_path / "export1"
    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(first_dir))

    store2, chats2, projects2, roadmaps2, nodes2, profile2 = _fresh_stores(tmp_path, "b")
    summary = import_from_directory(
        str(first_dir), store2, chats2, projects2, roadmaps2, nodes2, profile2
    )
    assert summary.created > 0
    assert summary.failed == 0

    restored_conversation = chats2.all()[0]
    restored = {e.query: e.summary for e in store2.by_conversation(restored_conversation.id)}
    assert restored == ADVERSARIAL_SUMMARIES

    second_dir = tmp_path / "export2"
    export_to_directory(store2, chats2, projects2, roadmaps2, nodes2, profile2, str(second_dir))
    first_files = {p.relative_to(first_dir): p.read_bytes() for p in first_dir.rglob("*") if p.is_file()}
    second_files = {
        p.relative_to(second_dir): p.read_bytes() for p in second_dir.rglob("*") if p.is_file()
    }
    assert first_files == second_files


def test_entry_with_empty_summary_round_trips_at_the_format_level(chats):
    """MemoryStore.add refuses an empty summary, so this can only be
    exercised through the pure build/parse functions directly - exactly
    the split export.py's own docstring describes them for."""
    conversation = chats.create("Empty")
    entry = Entry(
        id="e1", query="anything", summary="", sources=(),
        created_at="2026-01-01T00:00:00+00:00",
    )
    file1 = build_conversation_file(conversation, [entry], None, "empty")
    parsed = parse_conversation_file(file1.content, file1.path)

    assert len(parsed.entries) == 1
    assert parsed.entries[0].summary == NONE_YET

    restored_entry = entry.with_summary(parsed.entries[0].summary)
    file2 = build_conversation_file(conversation, [restored_entry], None, "empty")
    assert file1.content == file2.content


def test_legacy_export_without_length_prefixed_summaries_still_imports(
    tmp_path, store, chats, projects, roadmaps, nodes, profile
):
    """Exports written before summaries carried an explicit length (see
    export.py's `_meta_line`) must still import - restore.py detects the
    older `*created_at - kind*` meta line and falls back to the old
    parsing path for that file."""
    conversation = chats.create("Legacy")
    store.add("old question", "old answer", ["http://a"], conversation_id=conversation.id)
    out = tmp_path / "export"
    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(out))

    conv_file = next((out / "conversations").glob("*.md"))
    # Strip the trailing " - N" the current format adds, reproducing the
    # meta line as it looked before this fix.
    legacy_text = re.sub(r"^(\*.+) - \d+\*$", r"\1*", conv_file.read_text(), flags=re.MULTILINE)
    conv_file.write_text(legacy_text)

    store2, chats2, projects2, roadmaps2, nodes2, profile2 = _fresh_stores(tmp_path, "b")
    summary = import_from_directory(str(out), store2, chats2, projects2, roadmaps2, nodes2, profile2)

    assert summary.failed == 0
    assert summary.created > 0
    restored = store2.by_conversation(chats2.all()[0].id)
    assert restored[0].query == "old question"
    assert restored[0].summary == "old answer"
