"""Per-project "what's next" highlights.

Distinct from advice/planner.py, which summarizes everything stored and
writes prose. This is scoped to one project and deliberately terse: a few
concrete things worth doing, each traceable to a chat or document that
prompted it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from mindtrail.llm import LLMClient
from mindtrail.memory.store import Entry

MAX_HIGHLIGHTS = 5
SUMMARY_CHARS_PER_ENTRY = 400

SYSTEM_PROMPT = (
    "You surface what someone should do next in a piece of ongoing work.\n\n"
    "You are given their research, notes, and documents for one project, "
    "and optionally their own instructions for it.\n\n"
    "Return three to five highlights: short, concrete, and specific to "
    "this material. Each needs a headline of at most eight words and one "
    "sentence saying why it matters now. Ground every one in something "
    "actually present - name the document or question it came from. Skip "
    "generic advice that would apply to anyone.\n\n"
    'Respond with JSON only: {"highlights": [{"headline": "...", '
    '"detail": "...", "source": "..."}]} with no code fences.'
)


@dataclass(frozen=True)
class Highlight:
    headline: str
    detail: str
    source: str


def parse_highlights(text: str) -> list[Highlight]:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in highlights output: {text[:200]}")

    data = json.loads(payload[start : end + 1])
    raw = data.get("highlights", [])
    if not isinstance(raw, list):
        raise ValueError("'highlights' must be a list")

    parsed = [
        Highlight(
            headline=str(item["headline"]).strip(),
            detail=str(item.get("detail", "")).strip(),
            source=str(item.get("source", "")).strip(),
        )
        for item in raw
        if isinstance(item, dict) and str(item.get("headline", "")).strip()
    ]
    if not parsed:
        raise ValueError("no usable highlights returned")
    return parsed[:MAX_HIGHLIGHTS]


def _format_entries(entries: list[Entry]) -> str:
    lines = []
    for entry in entries:
        label = entry.kind.upper()
        lines.append(
            f"[{label}] {entry.query}: {entry.summary[:SUMMARY_CHARS_PER_ENTRY]}"
        )
    return "\n\n".join(lines)


def generate_highlights(
    llm: LLMClient, entries: list[Entry], instructions: str = ""
) -> list[Highlight]:
    """Raises ValueError when the project has nothing to reason about."""
    usable = [e for e in entries if e.kind != "advice"]
    if not usable:
        raise ValueError("nothing in this project yet")

    prefix = f"PROJECT INSTRUCTIONS:\n{instructions}\n\n" if instructions.strip() else ""
    completion = llm.complete(
        SYSTEM_PROMPT, f"{prefix}PROJECT MATERIAL:\n{_format_entries(usable)}",
        max_tokens=800,
    )
    return parse_highlights(completion.text)


def highlights_to_json(highlights: list[Highlight]) -> str:
    return json.dumps(
        [{"headline": h.headline, "detail": h.detail, "source": h.source} for h in highlights]
    )


def highlights_from_json(raw: str) -> list[Highlight]:
    """Rehydrate stored highlights, tolerating anything unparseable."""
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [
        Highlight(
            headline=str(d.get("headline", "")),
            detail=str(d.get("detail", "")),
            source=str(d.get("source", "")),
        )
        for d in data
        if isinstance(d, dict) and d.get("headline")
    ]
