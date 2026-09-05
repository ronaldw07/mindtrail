"""Parsing half of restoring a markdown export written by export.py.

The writer is the spec for the reader: every parse function here inverts
one `build_*` function in export.py exactly, field for field. Parsing is
pure - each `parse_*` function takes file text and returns a record,
never touching a filesystem or a store. `restore_apply.py` is the thin
orchestration layer on top that does the actual I/O and writes into the
stores, same split as export.py's `collect_export_files`/`write_export`.

Roadmap step dependencies are exported as titles, not ids (see
export.py) since ids are meaningless in a hand-readable document, and
this file just hands those titles back as strings - resolving them
against a roadmap's actual nodes happens in restore_apply.py, after
every node in that roadmap exists.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from mindtrail.organize.export import NONE_YET, ROADMAP_STATUS_ORDER

_META_LINE = re.compile(r"^\*(.*) - (.*)\*$")
_SOURCES_MARKER = "\n\n**Sources**\n"
_RECALLED_MARKER = "\n\n**Recalled entries**\n"
_STEP_FIELD_PREFIXES = (
    "- Note: ",
    "- Due: ",
    "- Depends on: ",
    "- Repeat: ",
    "- Linked entries: ",
)


@dataclass(frozen=True)
class ParsedEntry:
    query: str
    summary: str
    created_at: str
    kind: str
    sources: tuple[str, ...] = ()
    recalled_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedConversation:
    id: str
    title: str
    created_at: str
    updated_at: str
    project_name: str | None
    pinned: bool
    unread: bool
    entries: tuple[ParsedEntry, ...] = ()


@dataclass(frozen=True)
class ParsedProject:
    id: str
    name: str
    created_at: str
    instructions: str = ""


@dataclass(frozen=True)
class ParsedRoadmapStep:
    title: str
    detail: str
    status: str
    note: str
    due_date: str
    depends_on: tuple[str, ...] = ()
    repeat_days: int = 0
    linked_entries: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedRoadmap:
    id: str
    goal: str
    created_at: str
    steps: tuple[ParsedRoadmapStep, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ParsedProfile:
    content: str
    updated_at: str = ""


# --- frontmatter -----------------------------------------------------------


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Invert export.py's `_render`: a JSON scalar per line rather than a
    real YAML parser, matching the writer's own reasoning for avoiding one.
    """
    _, raw, tail = content.split("---\n", 2)
    frontmatter: dict = {}
    for line in raw.splitlines():
        if not line:
            continue
        key, _, value = line.partition(": ")
        frontmatter[key] = json.loads(value)
    body = tail.removeprefix("\n").rstrip("\n")
    return frontmatter, body


def _split_sections(body: str, marker: str) -> list[str]:
    """Split on a blank line followed by `marker`, keeping the marker
    with the section it starts. Mirrors how export.py joins sections and
    entries with "\\n\\n"."""
    return re.split(rf"\n\n(?={re.escape(marker)})", body)


def _parse_bullets(text: str) -> tuple[str, ...]:
    items = [line.removeprefix("- ") for line in text.splitlines() if line.startswith("- ")]
    return () if items == ["none"] else tuple(items)


# --- entries -----------------------------------------------------------


def _parse_meta_line(line: str, path: str) -> tuple[str, str]:
    match = _META_LINE.match(line)
    if not match:
        raise ValueError(f"{path}: malformed entry metadata line: {line!r}")
    return match.group(1), match.group(2)


def _parse_entry_block(block: str, path: str) -> ParsedEntry:
    """A conversation turn: query, timestamp/kind, summary, sources,
    and recalled ids. See export.py's `_entry_section`."""
    before_sources, _, after_sources = block.partition(_SOURCES_MARKER)
    sources_block, _, recalled_block = after_sources.partition(_RECALLED_MARKER)
    heading, meta, summary = before_sources.split("\n\n", 2)
    created_at, kind = _parse_meta_line(meta, path)
    return ParsedEntry(
        query=heading.removeprefix("## "),
        summary=summary,
        created_at=created_at,
        kind=kind,
        sources=_parse_bullets(sources_block),
        recalled_ids=_parse_bullets(recalled_block),
    )


def _parse_note_block(block: str, path: str) -> ParsedEntry:
    """An orphaned entry in notes.md - no sources/recalled section, see
    export.py's `build_notes_file`."""
    heading, meta, summary = block.split("\n\n", 2)
    created_at, kind = _parse_meta_line(meta, path)
    return ParsedEntry(query=heading.removeprefix("## "), summary=summary,
                        created_at=created_at, kind=kind)


def parse_notes_file(content: str, path: str = "notes.md") -> tuple[ParsedEntry, ...]:
    _, body = _parse_frontmatter(content)
    if body == NONE_YET:
        return ()
    return tuple(_parse_note_block(b, path) for b in _split_sections(body, "## "))


def parse_profile_file(content: str) -> ParsedProfile:
    fm, body = _parse_frontmatter(content)
    return ParsedProfile(
        content="" if body == NONE_YET else body,
        updated_at=fm.get("created_at", ""),
    )


def parse_conversation_file(content: str, path: str = "") -> ParsedConversation:
    fm, body = _parse_frontmatter(content)
    entries = (
        ()
        if body == NONE_YET
        else tuple(_parse_entry_block(b, path) for b in _split_sections(body, "## "))
    )
    return ParsedConversation(
        id=fm["id"],
        title=fm["title"],
        created_at=fm["created_at"],
        updated_at=fm["updated_at"],
        project_name=fm.get("project"),
        pinned=bool(fm.get("pinned", False)),
        unread=bool(fm.get("unread", False)),
        entries=entries,
    )


# --- projects and roadmaps -----------------------------------------------


def parse_project_index_file(content: str) -> ParsedProject:
    fm, body = _parse_frontmatter(content)
    instructions_block, _, _ = body.partition("\n\n## Highlights")
    instructions = instructions_block.removeprefix("## Instructions\n\n")
    return ParsedProject(
        id=fm["id"],
        name=fm["title"],
        created_at=fm["created_at"],
        instructions="" if instructions == NONE_YET else instructions,
    )


def _parse_step_block(block: str, status: str) -> ParsedRoadmapStep:
    lines = block.split("\n")
    title = lines[0].removeprefix("### ")
    field_start = next(i for i, line in enumerate(lines) if line.startswith("- Note: "))
    detail = "\n".join(lines[1:field_start]).strip()

    values = {}
    for prefix, line in zip(_STEP_FIELD_PREFIXES, lines[field_start:]):
        if not line.startswith(prefix):
            raise ValueError(f"expected {prefix!r}, got {line!r}")
        values[prefix] = line[len(prefix):]

    note = values["- Note: "]
    due = values["- Due: "]
    depends_raw = values["- Depends on: "]
    repeat_raw = values["- Repeat: "]
    linked_raw = values["- Linked entries: "]
    return ParsedRoadmapStep(
        title=title,
        detail=detail,
        status=status,
        note="" if note == "none" else note,
        due_date="" if due == "none" else due,
        depends_on=() if depends_raw == "none" else tuple(depends_raw.split(", ")),
        repeat_days=0 if repeat_raw == "none" else int(repeat_raw),
        linked_entries=() if linked_raw == "none" else tuple(linked_raw.split(", ")),
    )


def parse_roadmap_file(content: str) -> ParsedRoadmap | None:
    """None means this project has no roadmap - export.py writes an
    empty-id placeholder file for that case rather than omitting it."""
    fm, body = _parse_frontmatter(content)
    if not fm.get("id"):
        return None

    sections = _split_sections(body, "## ")  # sections[0] is "# Goal\n\n..."
    steps: list[ParsedRoadmapStep] = []
    for status, section in zip(ROADMAP_STATUS_ORDER, sections[1:]):
        _, _, rest = section.partition("\n\n")
        if rest == NONE_YET:
            continue
        steps.extend(_parse_step_block(b, status) for b in _split_sections(rest, "### "))

    return ParsedRoadmap(id=fm["id"], goal=fm["title"], created_at=fm["created_at"],
                          steps=tuple(steps))
