"""Markdown export: content generation, then the writer on top of it."""

from __future__ import annotations

import yaml
import pytest

from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.export import (
    ExportFile,
    SlugAllocator,
    build_conversation_file,
    collect_export_files,
    export_to_directory,
    slugify,
    write_export,
)
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import ProjectStore
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


def _frontmatter(content: str) -> dict:
    assert content.startswith("---\n")
    _, raw, _ = content.split("---\n", 2)
    return yaml.safe_load(raw)


# --- slugify ------------------------------------------------------------


def test_slugify_lowercases_and_hyphenates():
    assert slugify("My Great Chat") == "my-great-chat"


def test_slugify_collapses_runs_of_punctuation():
    assert slugify("what... is going on??") == "what-is-going-on"


def test_slugify_strips_leading_and_trailing_hyphens():
    assert slugify("--edge case--") == "edge-case"


def test_slugify_truncates_to_a_sane_length():
    assert len(slugify("x" * 500)) <= 60


def test_slugify_falls_back_when_nothing_survives():
    assert slugify("!!!") == "untitled"


def test_slugify_neutralises_path_traversal():
    slug = slugify("../../etc/passwd")
    assert "/" not in slug and ".." not in slug


# --- collision-safe filenames --------------------------------------------


def test_allocator_gives_distinct_slugs_to_two_untitled_conversations():
    allocator = SlugAllocator()
    a = allocator.allocate("conversations", "Untitled", "aaaa-1111")
    b = allocator.allocate("conversations", "Untitled", "bbbb-2222")
    assert a != b
    assert a == "untitled"
    assert b.startswith("untitled-")


def test_allocator_is_stable_across_calls_for_the_same_id():
    allocator = SlugAllocator()
    allocator.allocate("conversations", "Untitled", "aaaa-1111")
    first = allocator.allocate("conversations", "Untitled", "bbbb-2222")

    allocator2 = SlugAllocator()
    allocator2.allocate("conversations", "Untitled", "aaaa-1111")
    second = allocator2.allocate("conversations", "Untitled", "bbbb-2222")
    assert first == second


# --- frontmatter ----------------------------------------------------------


def test_conversation_frontmatter_has_required_fields(chats):
    conversation = chats.create("Hello")
    file = build_conversation_file(conversation, [], None, "hello")

    meta = _frontmatter(file.content)
    assert meta["id"] == conversation.id
    assert meta["title"] == "Hello"
    assert meta["created_at"] == conversation.created_at


def test_frontmatter_survives_quotes_and_newlines_in_the_title(chats):
    conversation = chats.create('A "tricky"\ntitle')
    file = build_conversation_file(conversation, [], None, "tricky")

    meta = _frontmatter(file.content)
    assert meta["title"] == conversation.title


# --- empty states -----------------------------------------------------


def test_empty_conversation_exports_a_none_yet_body(chats):
    conversation = chats.create("Quiet chat")
    file = build_conversation_file(conversation, [], None, "quiet-chat")

    assert "None yet" in file.content


def test_empty_profile_exports_without_crashing(store, chats, projects, roadmaps, nodes, profile):
    files = collect_export_files(store, chats, projects, roadmaps, nodes, profile)
    profile_file = next(f for f in files if f.path == "profile.md")
    assert "None yet" in profile_file.content


def test_project_with_no_roadmap_exports_a_none_yet_roadmap(
    store, chats, projects, roadmaps, nodes, profile
):
    project = projects.create("Bare Project")

    files = collect_export_files(store, chats, projects, roadmaps, nodes, profile)
    roadmap_file = next(f for f in files if f.path.endswith("roadmap.md"))
    assert "None yet" in roadmap_file.content


def test_export_with_nothing_at_all_does_not_crash(store, chats, projects, roadmaps, nodes, profile):
    files = collect_export_files(store, chats, projects, roadmaps, nodes, profile)
    paths = {f.path for f in files}
    assert paths == {"profile.md", "notes.md"}


# --- conversation content -------------------------------------------------


def test_conversation_turn_includes_question_summary_sources_and_recalled(
    store, chats
):
    conversation = chats.create("Research chat")
    first = store.add(
        "What is Kubernetes?",
        "A container orchestrator.",
        ["http://a"],
        conversation_id=conversation.id,
    )
    store.add(
        "How does it schedule pods?",
        "Via the scheduler.",
        ["http://b"],
        recalled_ids=[first.id],
        conversation_id=conversation.id,
    )
    entries = store.by_conversation(conversation.id)

    file = build_conversation_file(conversation, entries, None, "research-chat")

    assert "What is Kubernetes?" in file.content
    assert "A container orchestrator." in file.content
    assert "http://a" in file.content
    assert first.id in file.content


# --- roadmap dependencies rendered by title -------------------------------


def test_roadmap_dependencies_render_as_titles_not_ids(
    store, chats, projects, roadmaps, nodes, profile
):
    project = projects.create("Career")
    roadmap = roadmaps.create("Get a job", project_id=project.id)
    base = nodes.add(roadmap.id, "Learn SQL", status="accepted")
    dependent = nodes.add(roadmap.id, "Apply", status="proposed")
    nodes.set_depends_on(dependent.id, [base.id])

    files = collect_export_files(store, chats, projects, roadmaps, nodes, profile)
    roadmap_file = next(f for f in files if f.path.endswith("roadmap.md"))

    assert "Depends on: Learn SQL" in roadmap_file.content
    assert base.id not in roadmap_file.content


def test_roadmap_steps_are_grouped_by_status(
    store, chats, projects, roadmaps, nodes, profile
):
    project = projects.create("Career")
    roadmap = roadmaps.create("Get a job", project_id=project.id)
    nodes.add(roadmap.id, "Accepted step", status="accepted")
    nodes.add(roadmap.id, "Done step", status="done")
    nodes.add(roadmap.id, "Proposed step", status="proposed")
    nodes.add(roadmap.id, "Rejected step", status="rejected")

    files = collect_export_files(store, chats, projects, roadmaps, nodes, profile)
    content = next(f for f in files if f.path.endswith("roadmap.md")).content

    assert content.index("## Accepted") < content.index("Accepted step")
    assert content.index("## Done") < content.index("Done step")
    assert content.index("## Proposed") < content.index("Proposed step")
    assert content.index("## Rejected") < content.index("Rejected step")


# --- project filtering ------------------------------------------------


def test_project_filter_excludes_other_projects_and_global_files(
    store, chats, projects, roadmaps, nodes, profile
):
    keep = projects.create("Keep Me")
    drop = projects.create("Drop Me")
    kept_chat = chats.create("In scope", project_id=keep.id)
    chats.create("Out of scope", project_id=drop.id)
    chats.create("Unfiled")

    files = collect_export_files(
        store, chats, projects, roadmaps, nodes, profile, project_id=keep.id
    )
    paths = {f.path for f in files}

    assert "profile.md" not in paths
    assert "notes.md" not in paths
    assert any("keep-me" in p for p in paths)
    assert not any("drop-me" in p for p in paths)
    assert any(kept_chat.id in f.content for f in files if f.path.startswith("conversations/"))
    assert not any("out-of-scope" in p or "unfiled" in p for p in paths)


def test_project_filter_on_a_missing_project_raises(
    store, chats, projects, roadmaps, nodes, profile
):
    with pytest.raises(ValueError):
        collect_export_files(store, chats, projects, roadmaps, nodes, profile, project_id="nope")


# --- path safety -----------------------------------------------------


def test_malicious_title_lands_inside_the_output_directory(
    store, chats, projects, roadmaps, nodes, profile, tmp_path
):
    chats.create("../../etc/passwd")
    out_dir = tmp_path / "export_out"

    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(out_dir))

    written = list((out_dir / "conversations").iterdir())
    assert len(written) == 1
    assert written[0].parent == out_dir / "conversations"
    # Nothing escaped anywhere above the export root.
    assert not any(p.exists() for p in [tmp_path / "etc"])


# --- idempotent re-export -----------------------------------------------


def test_reexporting_unchanged_data_produces_identical_files(
    store, chats, projects, roadmaps, nodes, profile, tmp_path
):
    project = projects.create("Repeat")
    conversation = chats.create("Repeat chat", project_id=project.id)
    store.add("Q1", "A1", ["http://x"], conversation_id=conversation.id)
    roadmap = roadmaps.create("Goal", project_id=project.id)
    nodes.add(roadmap.id, "Step", status="accepted")
    profile.save("About me")

    out_dir = tmp_path / "export_out"
    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(out_dir))
    first_pass = {
        p: p.read_bytes() for p in out_dir.rglob("*") if p.is_file()
    }

    export_to_directory(store, chats, projects, roadmaps, nodes, profile, str(out_dir))
    second_pass = {
        p: p.read_bytes() for p in out_dir.rglob("*") if p.is_file()
    }

    assert first_pass.keys() == second_pass.keys()
    assert first_pass == second_pass


# --- writer ---------------------------------------------------------------


def test_write_export_creates_the_directory_tree(tmp_path):
    files = [ExportFile("a/b/c.md", "content")]
    out_dir = tmp_path / "nested" / "does" / "not" / "exist"

    count = write_export(files, str(out_dir))

    assert count == 1
    assert (out_dir / "a" / "b" / "c.md").read_text() == "content"
