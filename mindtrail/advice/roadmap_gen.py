"""Propose roadmap steps toward a stated goal.

Generation only ever adds or replaces *proposed* nodes. Accepted, done,
and rejected nodes - and every note - are never touched, so re-running
this after the user has made decisions plans around those decisions
instead of quietly overwriting them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from mindtrail.llm import LLMClient
from mindtrail.memory.store import Entry
from mindtrail.organize.roadmaps import RoadmapNode

MAX_NODES = 8
DETAIL_CHARS_PER_ENTRY = 300
GENERATION_MAX_TOKENS = 1800

SYSTEM_PROMPT = (
    "You break a goal into a small roadmap of concrete steps.\n\n"
    "You are given the user's profile (background, experience), material "
    "from a project (chats, notes, documents), and the state of their "
    "current roadmap if one exists - steps already accepted or marked "
    "done, steps they rejected, and any personal notes they attached.\n\n"
    "Propose 4 to 8 new steps. Do not re-propose anything already "
    "accepted, done, or rejected - build around those decisions instead. "
    "Respect their notes as constraints. Each step needs a short title "
    "(six words or fewer), a one or two sentence detail, and the titles "
    "of any other *proposed* steps in your list it depends on (empty if "
    "none - do not depend on already-accepted steps).\n\n"
    'Respond with JSON only: {"nodes": [{"title": "...", "detail": "...", '
    '"depends_on": ["other title"]}]} with no code fences.'
)


@dataclass(frozen=True)
class ProposedNode:
    title: str
    detail: str
    depends_on: tuple[str, ...]


def parse_proposal(text: str) -> list[ProposedNode]:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in roadmap output: {text[:200]}")

    data = json.loads(payload[start : end + 1])
    raw = data.get("nodes", [])
    if not isinstance(raw, list):
        raise ValueError("'nodes' must be a list")

    parsed = [
        ProposedNode(
            title=str(item["title"]).strip(),
            detail=str(item.get("detail", "")).strip(),
            depends_on=tuple(
                str(d).strip() for d in item.get("depends_on", []) if str(d).strip()
            ),
        )
        for item in raw
        if isinstance(item, dict) and str(item.get("title", "")).strip()
    ]
    if not parsed:
        raise ValueError("no usable roadmap steps returned")
    return parsed[:MAX_NODES]


def _format_project_material(entries: list[Entry]) -> str:
    if not entries:
        return ""
    lines = [
        f"[{e.kind.upper()}] {e.query}: {e.summary[:DETAIL_CHARS_PER_ENTRY]}"
        for e in entries
        if e.kind != "advice"
    ]
    return "PROJECT MATERIAL:\n" + "\n".join(lines) + "\n\n" if lines else ""


def _format_existing_nodes(
    nodes: list[RoadmapNode], linked_entries: dict[str, list[Entry]] | None = None
) -> str:
    if not nodes:
        return ""
    linked_entries = linked_entries or {}
    by_status: dict[str, list[str]] = {}
    for node in nodes:
        line = node.title
        if node.note:
            line += f" (user's note: {node.note})"
        for entry in linked_entries.get(node.id, []):
            line += f"\n  linked memory: {entry.query}: {entry.summary[:200]}"
        by_status.setdefault(node.status, []).append(line)

    sections = []
    for status in ("accepted", "done", "rejected"):
        if by_status.get(status):
            sections.append(f"{status.upper()}:\n" + "\n".join(by_status[status]))
    return "\n\n".join(sections) + "\n\n" if sections else ""


def generate_roadmap(
    llm: LLMClient,
    goal: str,
    profile: str = "",
    project_entries: list[Entry] | None = None,
    existing_nodes: list[RoadmapNode] | None = None,
    linked_entries: dict[str, list[Entry]] | None = None,
) -> list[ProposedNode]:
    """Raises ValueError for an empty goal.

    linked_entries maps an existing node's id to the memory entries
    linked to it (F6), shown alongside that node so a decided step's
    linked context can inform what gets proposed around it.
    """
    if not goal.strip():
        raise ValueError("a goal is required")

    prompt = (
        f"GOAL: {goal}\n\n"
        + (f"USER PROFILE:\n{profile}\n\n" if profile.strip() else "")
        + _format_existing_nodes(existing_nodes or [], linked_entries)
        + _format_project_material(project_entries or [])
    )
    completion = llm.complete(SYSTEM_PROMPT, prompt, max_tokens=GENERATION_MAX_TOKENS)
    return parse_proposal(completion.text)
