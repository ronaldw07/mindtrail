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

_META_LINE = re.compile(r"^\*(.*) - (.*) - (\d+)\*$")
_SOURCES_MARKER = "\n\n**Sources**\n"
_RECALLED_MARKER = "\n\n**Recalled entries**\n"
_RECALLED_HEADER = "**Recalled entries**\n"

# Exports written before the length-prefixed meta line (see export.py's
# `_meta_line`) end their meta line right after the kind, with no count.
# Both forms are handled: the legacy path keeps the old scan-for-the-next
# "## " heuristic, which is unreliable against a summary containing
# markdown of its own - that is exactly the bug the new format fixes -
# but there is no way to recover a length that was never written, so a
# legacy file gets the best-effort behavior it always had.
_META_LINE_LEGACY = re.compile(r"^\*(.*) - (.*)\*$")
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
class ParsedHighlight:
    headline: str
    priority: str
    detail: str


@dataclass(frozen=True)
class ParsedProject:
    id: str
    name: str
    created_at: str
    instructions: str = ""
    highlights: tuple[ParsedHighlight, ...] = ()


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
#
# A summary is LLM prose, not this file's own syntax, and it routinely
# contains markdown headings, tables, and "---" rules that look exactly
# like an entry boundary or a frontmatter fence. Splitting the body into
# entries first (by scanning for the next "## ") and only then parsing
# each piece - the original approach - breaks the moment a summary
# contains one of those constructs, because the scan cannot tell "the
# next entry starts here" from "this summary has a heading in it".
#
# The fix is to never scan the summary for a boundary at all. Every
# meta line now names the summary's exact character count (see
# export.py's `_meta_line`), so parsing walks the body positionally:
# read the heading, read the meta line, consume precisely that many
# characters as the summary regardless of what they contain, and
# whatever is left is either empty or the next entry's heading.


def _parse_meta_line(line: str, path: str) -> tuple[str, str, int]:
    match = _META_LINE.match(line)
    if not match:
        raise ValueError(f"{path}: malformed entry metadata line: {line!r}")
    created_at, kind, length = match.groups()
    return created_at, kind, int(length)


def _parse_meta_line_legacy(line: str, path: str) -> tuple[str, str]:
    match = _META_LINE_LEGACY.match(line)
    if not match:
        raise ValueError(f"{path}: malformed entry metadata line: {line!r}")
    return match.group(1), match.group(2)


def _is_legacy_format(body: str) -> bool:
    """True if `body` was written before summaries carried a length.

    Looking only at the first entry is enough: one file is always
    written by one version of export.py, so the format is consistent
    within it.
    """
    _, _, after_heading = body.partition("\n\n")
    meta, _, _ = after_heading.partition("\n\n")
    return bool(_META_LINE_LEGACY.match(meta)) and not _META_LINE.match(meta)


def _take_bullets(text: str) -> tuple[str, str]:
    """Consume the run of "- " bullet lines at the front of `text`,
    plus the blank line that follows them, returning (bullets, rest).

    Sources and recalled-entry ids are the app's own data - urls and
    uuids, one per line - never LLM prose, so unlike a summary they can
    safely be located by shape instead of needing a length prefix.
    """
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].startswith("- "):
        i += 1
    bullets = "\n".join(lines[:i])
    tail = lines[i:]
    if tail and tail[0] == "":
        tail = tail[1:]
    return bullets, "\n".join(tail)


def _consume_entry(text: str, path: str) -> tuple[ParsedEntry, str]:
    """Parse one conversation entry off the front of `text`. Returns the
    entry and whatever remains - empty, or the next entry's heading."""
    heading, sep, after_heading = text.partition("\n\n")
    if not sep or not heading.startswith("## "):
        raise ValueError(f"{path}: expected entry heading, got {heading!r}")
    meta, sep, after_meta = after_heading.partition("\n\n")
    if not sep:
        raise ValueError(f"{path}: malformed entry metadata line: {meta!r}")
    created_at, kind, length = _parse_meta_line(meta, path)
    if len(after_meta) < length:
        raise ValueError(
            f"{path}: entry summary shorter than its declared length "
            f"({len(after_meta)} < {length})"
        )
    summary, rest = after_meta[:length], after_meta[length:]

    if not rest.startswith(_SOURCES_MARKER):
        raise ValueError(f"{path}: expected sources section after summary, got {rest[:40]!r}")
    rest = rest[len(_SOURCES_MARKER):]
    sources_text, rest = _take_bullets(rest)

    if not rest.startswith(_RECALLED_HEADER):
        raise ValueError(f"{path}: expected recalled-entries section, got {rest[:40]!r}")
    rest = rest[len(_RECALLED_HEADER):]
    recalled_text, rest = _take_bullets(rest)

    entry = ParsedEntry(
        query=heading.removeprefix("## "),
        summary=summary,
        created_at=created_at,
        kind=kind,
        sources=_parse_bullets(sources_text),
        recalled_ids=_parse_bullets(recalled_text),
    )
    return entry, rest


def _consume_note(text: str, path: str) -> tuple[ParsedEntry, str]:
    """Parse one notes.md entry off the front of `text` - same idea as
    `_consume_entry` but without a sources/recalled section."""
    heading, sep, after_heading = text.partition("\n\n")
    if not sep or not heading.startswith("## "):
        raise ValueError(f"{path}: expected entry heading, got {heading!r}")
    meta, sep, after_meta = after_heading.partition("\n\n")
    if not sep:
        raise ValueError(f"{path}: malformed entry metadata line: {meta!r}")
    created_at, kind, length = _parse_meta_line(meta, path)
    if len(after_meta) < length:
        raise ValueError(
            f"{path}: entry summary shorter than its declared length "
            f"({len(after_meta)} < {length})"
        )
    summary, rest = after_meta[:length], after_meta[length:]
    rest = rest.removeprefix("\n\n") if rest else rest
    entry = ParsedEntry(query=heading.removeprefix("## "), summary=summary,
                         created_at=created_at, kind=kind)
    return entry, rest


def _parse_entry_block_legacy(block: str, path: str) -> ParsedEntry:
    """Pre-length-prefix format. Kept only so an export made before this
    fix can still be imported; still vulnerable to a summary containing
    markdown that looks like a boundary - there is no length recorded to
    fall back on."""
    before_sources, _, after_sources = block.partition(_SOURCES_MARKER)
    sources_block, _, recalled_block = after_sources.partition(_RECALLED_MARKER)
    heading, meta, summary = before_sources.split("\n\n", 2)
    created_at, kind = _parse_meta_line_legacy(meta, path)
    return ParsedEntry(
        query=heading.removeprefix("## "),
        summary=summary,
        created_at=created_at,
        kind=kind,
        sources=_parse_bullets(sources_block),
        recalled_ids=_parse_bullets(recalled_block),
    )


def _parse_note_block_legacy(block: str, path: str) -> ParsedEntry:
    heading, meta, summary = block.split("\n\n", 2)
    created_at, kind = _parse_meta_line_legacy(meta, path)
    return ParsedEntry(query=heading.removeprefix("## "), summary=summary,
                        created_at=created_at, kind=kind)


def _parse_entries(body: str, path: str) -> tuple[ParsedEntry, ...]:
    if _is_legacy_format(body):
        return tuple(_parse_entry_block_legacy(b, path) for b in _split_sections(body, "## "))
    entries: list[ParsedEntry] = []
    rest = body
    while rest:
        entry, rest = _consume_entry(rest, path)
        entries.append(entry)
    return tuple(entries)


def _parse_notes(body: str, path: str) -> tuple[ParsedEntry, ...]:
    if _is_legacy_format(body):
        return tuple(_parse_note_block_legacy(b, path) for b in _split_sections(body, "## "))
    entries: list[ParsedEntry] = []
    rest = body
    while rest:
        entry, rest = _consume_note(rest, path)
        entries.append(entry)
    return tuple(entries)


def parse_notes_file(content: str, path: str = "notes.md") -> tuple[ParsedEntry, ...]:
    _, body = _parse_frontmatter(content)
    if body == NONE_YET:
        return ()
    return _parse_notes(body, path)


def parse_profile_file(content: str) -> ParsedProfile:
    fm, body = _parse_frontmatter(content)
    return ParsedProfile(
        content="" if body == NONE_YET else body,
        updated_at=fm.get("created_at", ""),
    )


def parse_conversation_file(content: str, path: str = "") -> ParsedConversation:
    fm, body = _parse_frontmatter(content)
    entries = () if body == NONE_YET else _parse_entries(body, path)
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


# Matches export.py's `- **{headline}** ({priority}) - {detail}` line.
# `h.source` never made it into the export in the first place (only
# headline/priority/detail are rendered), so there is nothing to parse
# it back from - a restored highlight always carries an empty source.
_HIGHLIGHT_LINE = re.compile(r"^- \*\*(.*?)\*\* \((\w+)\) - (.*)$")


def _parse_highlights(text: str) -> tuple[ParsedHighlight, ...]:
    if text == NONE_YET:
        return ()
    parsed = []
    for line in text.splitlines():
        match = _HIGHLIGHT_LINE.match(line)
        if match:
            headline, priority, detail = match.groups()
            parsed.append(ParsedHighlight(headline=headline, priority=priority, detail=detail))
    return tuple(parsed)


def parse_project_index_file(content: str) -> ParsedProject:
    fm, body = _parse_frontmatter(content)
    instructions_block, _, highlights_block = body.partition("\n\n## Highlights\n\n")
    instructions = instructions_block.removeprefix("## Instructions\n\n")
    return ParsedProject(
        id=fm["id"],
        name=fm["title"],
        created_at=fm["created_at"],
        instructions="" if instructions == NONE_YET else instructions,
        highlights=_parse_highlights(highlights_block),
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
