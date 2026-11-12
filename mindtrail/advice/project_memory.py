"""A project's memory: what the assistant knows from its chats and files.

A short, plain summary kept on the project, shown on the project page and
handed to every new chat in it, so a fresh chat starts from what earlier
ones established instead of from nothing.
"""

from __future__ import annotations

from mindtrail.llm import LLMClient
from mindtrail.memory.store import Entry

SUMMARY_CHARS_PER_ENTRY = 400
GENERATION_MAX_TOKENS = 700
MAX_MEMORY_CHARS = 2000

SYSTEM_PROMPT = (
    "You keep the memory for one project in someone's notes app: a short "
    "summary of what is known from their chats and documents in it.\n\n"
    "Write 3 to 8 bullet points, each one line, starting with '- '. Cover "
    "their goal for the project, decisions made, facts about their "
    "situation, and open questions. Be specific to this material; skip "
    "anything generic. Under 150 words.\n\n"
    "If a previous memory is given, update it: keep what still holds "
    "(the person may have written some of it by hand), fold in what is "
    "new, and drop only what the new material contradicts.\n\n"
    "Return only the bullets, no heading or preamble."
)


def _format_entries(entries: list[Entry]) -> str:
    return "\n\n".join(
        f"[{e.kind.upper()}] {e.query}: {e.summary[:SUMMARY_CHARS_PER_ENTRY]}"
        for e in entries
    )


def generate_memory(
    llm: LLMClient, entries: list[Entry], previous: str = "", instructions: str = ""
) -> str:
    """Raises ValueError when the project has nothing to remember."""
    usable = [e for e in entries if e.kind != "advice"]
    if not usable:
        raise ValueError("nothing in this project yet")

    prefix = ""
    if instructions.strip():
        prefix += f"PROJECT INSTRUCTIONS:\n{instructions}\n\n"
    if previous.strip():
        prefix += f"PREVIOUS MEMORY:\n{previous}\n\n"
    completion = llm.complete(
        SYSTEM_PROMPT,
        f"{prefix}PROJECT MATERIAL:\n{_format_entries(usable)}",
        max_tokens=GENERATION_MAX_TOKENS,
    )
    text = completion.text.strip()
    if not text:
        raise ValueError("the model returned an empty memory")
    return text[:MAX_MEMORY_CHARS]
