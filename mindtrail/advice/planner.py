"""Synthesize a next-steps plan from everything stored.

Reuses the same memory store as research, notes, and documents - the
planner does not go fetch anything new, it only reads what already
accumulated there. That keeps it cheap (one completion) and means it can
only recommend things actually grounded in stored material.
"""

from __future__ import annotations

from dataclasses import dataclass

from mindtrail.llm import LLMClient
from mindtrail.memory.store import Entry

SYSTEM_PROMPT = (
    "You are a planning assistant. You are given someone's uploaded "
    "documents (e.g. a resume), their manual notes, and a summary of what "
    "they've researched recently.\n\n"
    "Write a short situation summary, then 3-6 prioritized action items. "
    "Ground every item in something specific from what you were given - "
    "cite the document, note, or research topic it comes from. Do not give "
    "generic advice that isn't tied to the actual material provided."
)

MAX_SUMMARY_CHARS_PER_ENTRY = 500


@dataclass(frozen=True)
class Advice:
    text: str
    tokens: int


def _format_section(label: str, entries: list[Entry]) -> str:
    if not entries:
        return ""
    lines = [
        f"- {e.query}: {e.summary[:MAX_SUMMARY_CHARS_PER_ENTRY]}" for e in entries
    ]
    return f"{label}:\n" + "\n".join(lines) + "\n\n"


def generate_advice(llm: LLMClient, entries: list[Entry]) -> Advice:
    """Raises ValueError if there is nothing to base advice on."""
    documents = [e for e in entries if e.kind == "document"]
    notes = [e for e in entries if e.kind == "note"]
    research = [e for e in entries if e.kind == "research"]

    if not (documents or notes or research):
        raise ValueError(
            "nothing stored yet - add a document, note, or ask a question first"
        )

    prompt = (
        _format_section("DOCUMENTS", documents)
        + _format_section("NOTES", notes)
        + _format_section("RESEARCH", research)
    )
    completion = llm.complete(SYSTEM_PROMPT, prompt, max_tokens=900)
    return Advice(text=completion.text, tokens=completion.tokens)
