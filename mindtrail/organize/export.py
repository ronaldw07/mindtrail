"""Export everything to plain markdown with YAML frontmatter.

This is the whole backup and portability story: mindtrail otherwise has
no way to leave the SQLite file and the Chroma directory it lives in.
Content generation is pure - every `build_*` function takes already-loaded
records and returns an (ExportFile) pair, so the tests exercise formatting
and slug collisions without ever touching a filesystem. `write_export` is
the one function that does I/O, and it is a thin loop over the pairs.

Filenames are derived from titles, which are free text a user can set to
anything - including something that looks like a path. Slugifying strips
every character but lowercase letters, digits, and hyphens, so a title of
"../../etc/passwd" collapses to "etc-passwd" and can never climb out of
the output directory.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from mindtrail import config
from mindtrail.advice.highlights import highlights_from_json
from mindtrail.memory.store import Entry, MemoryStore
from mindtrail.organize.conversations import Conversation, ConversationStore
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import Project, ProjectStore
from mindtrail.organize.roadmaps import Roadmap, RoadmapNode, RoadmapNodeStore, RoadmapStore

SLUG_MAX_CHARS = 60
SLUG_FALLBACK = "untitled"
_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")

# Steps read top to bottom as "what's actually happening": in progress,
# then finished, then still-undecided, with rejected trailing at the
# bottom - the same priority the canvas tidy-up already uses.
ROADMAP_STATUS_ORDER = ("accepted", "done", "proposed", "rejected")
ROADMAP_STATUS_HEADINGS = {
    "accepted": "Accepted",
    "done": "Done",
    "proposed": "Proposed",
    "rejected": "Rejected",
}

NONE_YET = "_None yet._"


@dataclass(frozen=True)
class ExportFile:
    """One file to write: a path relative to the export root, and its
    full text content, frontmatter included."""

    path: str
    content: str


def slugify(title: str, fallback: str = SLUG_FALLBACK) -> str:
    lowered = title.strip().lower()
    slug = _SLUG_UNSAFE.sub("-", lowered).strip("-")[:SLUG_MAX_CHARS].strip("-")
    return slug or fallback


class SlugAllocator:
    """Deterministic, collision-safe filenames within one export run.

    A collision is broken with the record's own id rather than a running
    counter, so the same two records get the same two filenames on every
    re-export regardless of iteration order - a counter would only be
    stable if nothing about the data ever changed between runs.
    """

    def __init__(self) -> None:
        self._used: dict[str, set[str]] = {}

    def allocate(self, namespace: str, title: str, record_id: str) -> str:
        base = slugify(title)
        used = self._used.setdefault(namespace, set())
        if base not in used:
            used.add(base)
            return base
        suffixed = f"{base}-{record_id[:8]}"
        used.add(suffixed)
        return suffixed


def _render(frontmatter: dict, body: str) -> str:
    """YAML frontmatter plus a markdown body.

    Every value goes through json.dumps rather than an ad-hoc quoting
    scheme - a double-quoted JSON scalar is also valid YAML, so this
    stays parseable by a real YAML reader without pulling one in here.
    """
    lines = ["---"]
    lines.extend(f"{key}: {json.dumps(value)}" for key, value in frontmatter.items())
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip())
    return "\n".join(lines) + "\n"


# --- profile and notes ------------------------------------------------


def build_profile_file(profile: ProfileStore) -> ExportFile:
    p = profile.get()
    frontmatter = {
        "id": "profile",
        "title": "Profile",
        "created_at": p.updated_at,
    }
    body = p.content.strip() if not p.is_empty else NONE_YET
    return ExportFile("profile.md", _render(frontmatter, body))


def build_notes_file(orphaned_entries: list[Entry]) -> ExportFile:
    """Entries that belong to no conversation at all - documents and
    advice stored through the CLI, which never files them into one.
    Everything else already appears inside its conversation's file."""
    frontmatter = {
        "id": "notes",
        "title": "Notes",
        "created_at": "",
    }
    if not orphaned_entries:
        body = NONE_YET
    else:
        sections = []
        for e in sorted(orphaned_entries, key=lambda e: e.created_at):
            sections.append(
                f"## {e.query or '(untitled)'}\n\n"
                f"*{e.created_at} - {e.kind}*\n\n"
                f"{e.summary.strip() or NONE_YET}"
            )
        body = "\n\n".join(sections)
    return ExportFile("notes.md", _render(frontmatter, body))


# --- conversations ------------------------------------------------------


def _bullet_list(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- none"]


def _entry_section(entry: Entry) -> str:
    lines = [
        f"## {entry.query or '(untitled)'}",
        "",
        f"*{entry.created_at} - {entry.kind}*",
        "",
        entry.summary.strip() or NONE_YET,
        "",
        "**Sources**",
        *_bullet_list(list(entry.sources)),
        "",
        "**Recalled entries**",
        *_bullet_list(list(entry.recalled_ids)),
    ]
    return "\n".join(lines)


def build_conversation_file(
    conversation: Conversation,
    entries: list[Entry],
    project_name: str | None,
    slug: str,
) -> ExportFile:
    frontmatter = {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "project": project_name,
        "pinned": conversation.pinned,
        "unread": conversation.unread,
    }
    ordered = sorted(entries, key=lambda e: e.created_at)
    body = "\n\n".join(_entry_section(e) for e in ordered) if ordered else NONE_YET
    return ExportFile(f"conversations/{slug}.md", _render(frontmatter, body))


# --- projects -------------------------------------------------------------


def build_project_index_file(project: Project, slug: str) -> ExportFile:
    frontmatter = {
        "id": project.id,
        "title": project.name,
        "created_at": project.created_at,
    }
    highlights = highlights_from_json(project.advice)
    highlight_lines = (
        "\n".join(f"- **{h.headline}** ({h.priority}) - {h.detail}" for h in highlights)
        if highlights
        else NONE_YET
    )
    body = (
        f"## Instructions\n\n{project.instructions.strip() or NONE_YET}\n\n"
        f"## Highlights\n\n{highlight_lines}"
    )
    return ExportFile(f"projects/{slug}/index.md", _render(frontmatter, body))


def _step_block(node: RoadmapNode, titles_by_id: dict[str, str]) -> str:
    dep_titles = [titles_by_id[d] for d in node.depends_on if d in titles_by_id]
    lines = [f"### {node.title}"]
    if node.detail.strip():
        lines.append(node.detail.strip())
    lines.append(f"- Note: {node.note.strip() or 'none'}")
    lines.append(f"- Due: {node.due_date or 'none'}")
    lines.append(f"- Depends on: {', '.join(dep_titles) if dep_titles else 'none'}")
    return "\n".join(lines)


def build_roadmap_file(
    project: Project, roadmap: Roadmap | None, nodes: list[RoadmapNode], slug: str
) -> ExportFile:
    if roadmap is None:
        frontmatter = {"id": "", "title": f"{project.name} roadmap", "created_at": ""}
        return ExportFile(f"projects/{slug}/roadmap.md", _render(frontmatter, NONE_YET))

    frontmatter = {"id": roadmap.id, "title": roadmap.goal, "created_at": roadmap.created_at}
    titles_by_id = {n.id: n.title for n in nodes}
    by_status: dict[str, list[RoadmapNode]] = {s: [] for s in ROADMAP_STATUS_ORDER}
    for n in nodes:
        by_status.setdefault(n.status, []).append(n)

    sections = [f"# Goal\n\n{roadmap.goal}"]
    for status in ROADMAP_STATUS_ORDER:
        items = by_status.get(status, [])
        heading = f"## {ROADMAP_STATUS_HEADINGS[status]}"
        body = (
            "\n\n".join(_step_block(n, titles_by_id) for n in items) if items else NONE_YET
        )
        sections.append(f"{heading}\n\n{body}")

    return ExportFile(f"projects/{slug}/roadmap.md", _render(frontmatter, "\n\n".join(sections)))


# --- orchestration --------------------------------------------------------


def default_export_dir() -> str:
    """Sits beside the Chroma directory and the SQLite file, same
    reasoning as organize/db.py's default_db_path: everything that makes
    up "the data" lives together so it moves together."""
    return str(Path(config.CHROMA_DIR).parent / "mindtrail_export")


def collect_export_files(
    store: MemoryStore,
    chats: ConversationStore,
    projects: ProjectStore,
    roadmaps: RoadmapStore,
    nodes: RoadmapNodeStore,
    profile: ProfileStore,
    project_id: str | None = None,
) -> list[ExportFile]:
    """Build every file for this export, writing nothing.

    With project_id set, profile.md and notes.md are skipped along with
    every other project - both are global content that has no home
    inside a single project's export.
    """
    by_conversation: dict[str, list[Entry]] = {}
    for entry in store.all():
        by_conversation.setdefault(entry.conversation_id, []).append(entry)

    allocator = SlugAllocator()
    files: list[ExportFile] = []

    if project_id is None:
        files.append(build_profile_file(profile))
        files.append(build_notes_file(by_conversation.get("", [])))
        target_projects = projects.all()
        conversations = chats.all()
    else:
        scoped = projects.get(project_id)
        if scoped is None:
            raise ValueError(f"no such project: {project_id}")
        target_projects = [scoped]
        conversations = chats.in_project(project_id)

    for conversation in conversations:
        slug = allocator.allocate("conversations", conversation.title, conversation.id)
        project_name = None
        if conversation.project_id:
            proj = projects.get(conversation.project_id)
            project_name = proj.name if proj else None
        files.append(
            build_conversation_file(
                conversation, by_conversation.get(conversation.id, []), project_name, slug
            )
        )

    for project in target_projects:
        slug = allocator.allocate("projects", project.name, project.id)
        files.append(build_project_index_file(project, slug))
        roadmap = roadmaps.for_project(project.id)
        roadmap_nodes = nodes.for_roadmap(roadmap.id) if roadmap is not None else []
        files.append(build_roadmap_file(project, roadmap, roadmap_nodes, slug))

    return files


def write_export(files: list[ExportFile], out_dir: str) -> int:
    """Write every file under out_dir, creating directories as needed.

    Each write overwrites in place, so re-running an unchanged export
    reproduces byte-identical files instead of accumulating duplicates -
    there is nothing here to accumulate, since the filename for a given
    record is a pure function of its own (stable) title and id.
    """
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    for file in files:
        target = root / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.content, encoding="utf-8")
    return len(files)


def export_to_directory(
    store: MemoryStore,
    chats: ConversationStore,
    projects: ProjectStore,
    roadmaps: RoadmapStore,
    nodes: RoadmapNodeStore,
    profile: ProfileStore,
    out_dir: str,
    project_id: str | None = None,
) -> int:
    files = collect_export_files(store, chats, projects, roadmaps, nodes, profile, project_id)
    return write_export(files, out_dir)
