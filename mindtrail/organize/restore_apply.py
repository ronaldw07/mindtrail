"""Writer half of restoring a markdown export: walks the directory tree
`export.py` produces and writes what `restore.py` parses into the stores.

Deliberately no web API endpoint for this. Restore overwrites or merges
into a live database; a button in the UI inviting someone to do that by
accident is the wrong affordance for something this destructive. It stays
a CLI-only, deliberate, out-of-band operation - see cli.py's `cmd_import`.

Idempotent by id: every exported file carries the id of the record it
came from in its frontmatter. If that id already exists in the target
database, the file is skipped (unless --overwrite). This is also why
ProjectStore, ConversationStore, and RoadmapStore each grew a `restore`
method - the normal `create` always mints a fresh id, which would make a
second run of the same import duplicate everything it already restored.

Roadmap nodes are created in two passes, exactly like
web/api.py's handle_apply_template: first every node, building a
title-to-id map scoped to that one roadmap, then depends_on is resolved
against that map. A title that does not resolve is dropped with a
warning, not an error - a hand-edited export should not crash the import
over one broken reference.

Conversation entries are re-added through MemoryStore.add rather than
written straight into Chroma, so they re-embed exactly like a fresh
`ask` or `note` would (see MemoryStore.update_entry for the precedent:
a plain metadata write would leave semantic search matching nothing,
since Chroma embeds the document text once, at write time).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import Conversation, ConversationStore
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import Project, ProjectStore
from mindtrail.organize.restore import (
    parse_conversation_file,
    parse_notes_file,
    parse_profile_file,
    parse_project_index_file,
    parse_roadmap_file,
)
from mindtrail.organize.roadmaps import Roadmap, RoadmapNodeStore, RoadmapStore


@dataclass(frozen=True)
class ImportSummary:
    """How one import run went. Combined with `+` across every file."""

    created: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: tuple[str, ...] = ()

    def __add__(self, other: "ImportSummary") -> "ImportSummary":
        return ImportSummary(
            created=self.created + other.created,
            skipped=self.skipped + other.skipped,
            failed=self.failed + other.failed,
            warnings=self.warnings + other.warnings,
        )


def _iter_files(root: Path, pattern: str) -> list[Path]:
    return sorted(root.glob(pattern))


def _import_projects(
    root: Path, projects: ProjectStore, overwrite: bool
) -> tuple[ImportSummary, dict[str, str], dict[str, str]]:
    """Returns the summary plus two lookup maps built along the way:
    folder slug -> project id (roadmap.md sits beside index.md, so the
    link is positional) and project name -> id (a conversation's
    frontmatter only records its project by name)."""
    created = skipped = failed = 0
    warnings: list[str] = []
    slug_to_id: dict[str, str] = {}
    name_to_id: dict[str, str] = {}

    for path in _iter_files(root, "projects/*/index.md"):
        try:
            parsed = parse_project_index_file(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failed += 1
            warnings.append(f"{path}: could not parse project ({exc})")
            continue

        slug_to_id[path.parent.name] = parsed.id
        name_to_id[parsed.name] = parsed.id

        existing = projects.get(parsed.id)
        if existing is not None and not overwrite:
            skipped += 1
            continue
        if existing is not None:
            projects.rename(parsed.id, parsed.name)
            projects.set_instructions(parsed.id, parsed.instructions)
        else:
            projects.restore(Project(id=parsed.id, name=parsed.name,
                                      created_at=parsed.created_at))
            if parsed.instructions:
                projects.set_instructions(parsed.id, parsed.instructions)
        created += 1

    return ImportSummary(created, skipped, failed, tuple(warnings)), slug_to_id, name_to_id


def _import_roadmaps(
    root: Path,
    roadmaps: RoadmapStore,
    nodes: RoadmapNodeStore,
    slug_to_id: dict[str, str],
    overwrite: bool,
) -> ImportSummary:
    created = skipped = failed = 0
    warnings: list[str] = []

    for path in _iter_files(root, "projects/*/roadmap.md"):
        try:
            parsed = parse_roadmap_file(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failed += 1
            warnings.append(f"{path}: could not parse roadmap ({exc})")
            continue
        if parsed is None:
            continue  # "no roadmap" placeholder - nothing to restore

        project_id = slug_to_id.get(path.parent.name)
        if project_id is None:
            failed += 1
            warnings.append(f"{path}: no matching project, skipped")
            continue

        existing = roadmaps.get(parsed.id)
        if existing is not None and not overwrite:
            skipped += 1
            continue
        if existing is not None:
            roadmaps.delete(parsed.id)  # cascades to its own nodes only

        roadmap = roadmaps.restore(
            Roadmap(id=parsed.id, project_id=project_id, goal=parsed.goal,
                    created_at=parsed.created_at)
        )

        title_to_id: dict[str, str] = {}
        for step in parsed.steps:
            node = nodes.add(
                roadmap.id, step.title, step.detail, status=step.status,
                due_date=step.due_date, repeat_days=step.repeat_days,
                linked_entries=list(step.linked_entries),
            )
            if step.note:
                nodes.set_note(node.id, step.note)
            title_to_id[step.title] = node.id

        for step in parsed.steps:
            deps = []
            for title in step.depends_on:
                dep_id = title_to_id.get(title)
                if dep_id is None:
                    warnings.append(
                        f"{path}: dependency '{title}' for step "
                        f"'{step.title}' not found, dropped"
                    )
                    continue
                deps.append(dep_id)
            if deps:
                nodes.set_depends_on(title_to_id[step.title], deps)

        created += 1

    return ImportSummary(created, skipped, failed, tuple(warnings))


def _import_conversations(
    root: Path,
    chats: ConversationStore,
    store: MemoryStore,
    name_to_id: dict[str, str],
    overwrite: bool,
) -> ImportSummary:
    created = skipped = failed = 0
    warnings: list[str] = []

    for path in _iter_files(root, "conversations/*.md"):
        try:
            parsed = parse_conversation_file(path.read_text(encoding="utf-8"), str(path))
        except Exception as exc:
            failed += 1
            warnings.append(f"{path}: could not parse conversation ({exc})")
            continue

        existing = chats.get(parsed.id)
        if existing is not None and not overwrite:
            skipped += 1
            continue
        if existing is not None:
            store.delete_conversation_entries(parsed.id)
            chats.delete(parsed.id)

        project_id = None
        if parsed.project_name is not None:
            project_id = name_to_id.get(parsed.project_name)
            if project_id is None:
                warnings.append(
                    f"{path}: project '{parsed.project_name}' not found, "
                    "leaving unfiled"
                )

        conversation = chats.restore(
            Conversation(
                id=parsed.id, title=parsed.title, project_id=project_id,
                pinned=parsed.pinned, unread=parsed.unread,
                created_at=parsed.created_at, updated_at=parsed.updated_at,
            )
        )
        for entry in parsed.entries:
            store.add(
                entry.query, entry.summary, list(entry.sources),
                kind=entry.kind, conversation_id=conversation.id,
                recalled_ids=list(entry.recalled_ids), created_at=entry.created_at,
            )
        created += 1

    return ImportSummary(created, skipped, failed, tuple(warnings))


def _import_profile(root: Path, profile: ProfileStore, overwrite: bool) -> ImportSummary:
    path = root / "profile.md"
    if not path.exists():
        return ImportSummary()
    try:
        parsed = parse_profile_file(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ImportSummary(failed=1, warnings=(f"{path}: could not parse profile ({exc})",))

    if not parsed.content:
        return ImportSummary(skipped=1)
    if not profile.get().is_empty and not overwrite:
        return ImportSummary(skipped=1)

    profile.save(parsed.content, updated_at=parsed.updated_at or None)
    return ImportSummary(created=1)


def _import_notes(root: Path, store: MemoryStore, overwrite: bool) -> ImportSummary:
    path = root / "notes.md"
    if not path.exists():
        return ImportSummary()
    try:
        entries = parse_notes_file(path.read_text(encoding="utf-8"), str(path))
    except Exception as exc:
        return ImportSummary(failed=1, warnings=(f"{path}: could not parse notes ({exc})",))
    if not entries:
        return ImportSummary(skipped=1)

    orphaned = [e for e in store.all() if not e.conversation_id]
    if orphaned:
        if not overwrite:
            return ImportSummary(skipped=1)
        for entry in orphaned:
            store.delete_entry(entry.id)

    for entry in entries:
        store.add(entry.query, entry.summary, [], kind=entry.kind, created_at=entry.created_at)
    return ImportSummary(created=1)


def import_from_directory(
    root_dir: str,
    store: MemoryStore,
    chats: ConversationStore,
    projects: ProjectStore,
    roadmaps: RoadmapStore,
    nodes: RoadmapNodeStore,
    profile: ProfileStore,
    overwrite: bool = False,
) -> ImportSummary:
    """Restore everything under `root_dir` (an export.py output tree)
    into the given stores. Projects and roadmaps go first, since a
    conversation resolves its project by name and a roadmap step
    resolves its dependencies by title - both need the thing they
    reference to already exist.
    """
    root = Path(root_dir)
    project_summary, slug_to_id, name_to_id = _import_projects(root, projects, overwrite)
    total = project_summary
    total += _import_roadmaps(root, roadmaps, nodes, slug_to_id, overwrite)
    total += _import_conversations(root, chats, store, name_to_id, overwrite)
    total += _import_profile(root, profile, overwrite)
    total += _import_notes(root, store, overwrite)
    return total
