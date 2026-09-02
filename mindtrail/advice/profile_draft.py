"""Draft a starting profile from documents and notes already stored.

A blank textarea is where good intentions die. This gives the user
something to edit rather than something to write from scratch - it is
explicitly a draft, and the user's own edit always wins on every
subsequent save.
"""

from __future__ import annotations

from mindtrail.llm import LLMClient
from mindtrail.memory.store import Entry

SYSTEM_PROMPT = (
    "Draft a first-person profile from the documents and notes below - "
    "background, education, skills, and what they seem to be working "
    "toward. Write plainly, three to six sentences, as something the "
    "person would read and edit themselves. State only what the material "
    "actually supports; do not invent specifics it does not contain."
)
DETAIL_CHARS_PER_ENTRY = 600
DRAFT_MAX_TOKENS = 500


def draft_profile(llm: LLMClient, entries: list[Entry]) -> str:
    """Raises ValueError if there is nothing to draft from."""
    usable = [e for e in entries if e.kind in ("document", "note")]
    if not usable:
        raise ValueError("no documents or notes to draft a profile from")

    lines = [
        f"[{e.kind.upper()}] {e.query}: {e.summary[:DETAIL_CHARS_PER_ENTRY]}"
        for e in usable
    ]
    completion = llm.complete(
        SYSTEM_PROMPT, "\n\n".join(lines), max_tokens=DRAFT_MAX_TOKENS
    )
    return completion.text.strip()
