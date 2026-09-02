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
# Five highlights with detail and sources overran 800 tokens and the JSON
# came back truncated mid-object, so parsing failed on otherwise good
# output. Sized with headroom rather than trimmed to fit.
GENERATION_MAX_TOKENS = 1600

PRIORITIES = ("now", "next", "later")
DEFAULT_PRIORITY = "next"

SYSTEM_PROMPT = (
    "You surface what someone should do next in a piece of ongoing work.\n\n"
    "You are given their research, notes, and documents for one project, "
    "and optionally their own instructions for it.\n\n"
    "Return three to five highlights: short, concrete, and specific to "
    "this material. Each needs a headline of at most eight words, a "
    "detail of at most two sentences, and a priority. Keep detail tight - "
    "long entries crowd out the later highlights.\n\n"
    "Priority is one of:\n"
    '  "now"   - the single most pressing thing, given what they have '
    "been asking about most recently. Use this sparingly, ideally once.\n"
    '  "next"  - clearly worth doing soon.\n'
    '  "later" - worth remembering but not urgent.\n\n'
    "Ground every one in something actually present - name the document "
    "or question it came from. Skip generic advice that would apply to "
    "anyone.\n\n"
    'Respond with JSON only: {"highlights": [{"headline": "...", '
    '"detail": "...", "source": "...", "priority": "now"}]} '
    "with no code fences."
)


@dataclass(frozen=True)
class Highlight:
    headline: str
    detail: str
    source: str
    priority: str = DEFAULT_PRIORITY


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
            priority=_clean_priority(item.get("priority")),
        )
        for item in raw
        if isinstance(item, dict) and str(item.get("headline", "")).strip()
    ]
    if not parsed:
        raise ValueError("no usable highlights returned")
    return sort_by_priority(parsed)[:MAX_HIGHLIGHTS]


def _clean_priority(value) -> str:
    """Unrecognised priorities fall back rather than breaking ordering."""
    cleaned = str(value or "").strip().lower()
    return cleaned if cleaned in PRIORITIES else DEFAULT_PRIORITY


def sort_by_priority(highlights: list[Highlight]) -> list[Highlight]:
    """Most pressing first, preserving the model's order within a tier."""
    return sorted(highlights, key=lambda h: PRIORITIES.index(h.priority))


def _format_entries(entries: list[Entry]) -> str:
    lines = []
    for entry in entries:
        label = entry.kind.upper()
        lines.append(
            f"[{label}] {entry.query}: {entry.summary[:SUMMARY_CHARS_PER_ENTRY]}"
        )
    return "\n\n".join(lines)


def generate_highlights(
    llm: LLMClient, entries: list[Entry], instructions: str = "", profile: str = ""
) -> list[Highlight]:
    """Raises ValueError when the project has nothing to reason about."""
    usable = [e for e in entries if e.kind != "advice"]
    if not usable:
        raise ValueError("nothing in this project yet")

    prefix = ""
    if profile.strip():
        prefix += f"ABOUT THE USER:\n{profile}\n\n"
    if instructions.strip():
        prefix += f"PROJECT INSTRUCTIONS:\n{instructions}\n\n"
    completion = llm.complete(
        SYSTEM_PROMPT,
        f"{prefix}PROJECT MATERIAL:\n{_format_entries(usable)}",
        max_tokens=GENERATION_MAX_TOKENS,
    )
    return parse_highlights(completion.text)


def highlights_to_json(highlights: list[Highlight]) -> str:
    return json.dumps(
        [
            {
                "headline": h.headline,
                "detail": h.detail,
                "source": h.source,
                "priority": h.priority,
            }
            for h in highlights
        ]
    )


def highlights_from_json(raw: str) -> list[Highlight]:
    """Rehydrate stored highlights, tolerating anything unparseable."""
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return sort_by_priority(
        [
            Highlight(
                headline=str(d.get("headline", "")),
                detail=str(d.get("detail", "")),
                source=str(d.get("source", "")),
                priority=_clean_priority(d.get("priority")),
            )
            for d in data
            if isinstance(d, dict) and d.get("headline")
        ]
    )
