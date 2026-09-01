"""Assign a topic label and extract key facts from a synthesis.

Run once per `ask`, after the answer is written. The model is shown the
topics already in use and asked to reuse one when it fits, since minting a
fresh label every time would fragment a handful of real topics into dozens
of near-duplicates.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from mindtrail.llm import LLMClient

SYSTEM_PROMPT = (
    "You organize a research memory. Given a question and its answer, "
    "assign a short topic label (two to four words, Title Case) and list "
    "three to five key facts as short standalone sentences.\n\n"
    "You will be shown topic labels already in use. Reuse one if it "
    "genuinely fits, rather than creating a near-duplicate. Only propose a "
    "new label when nothing existing fits.\n\n"
    'Respond with JSON only: {"topic": "...", "key_facts": ["...", "..."]} '
    "with no surrounding prose or code fences."
)

MIN_KEY_FACTS = 1
MAX_KEY_FACTS = 5


@dataclass(frozen=True)
class TopicAssignment:
    topic: str
    key_facts: tuple[str, ...]


def parse_assignment(text: str) -> TopicAssignment:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in topic output: {text[:200]}")

    data = json.loads(payload[start : end + 1])
    topic = str(data.get("topic", "")).strip()
    if not topic:
        raise ValueError("model returned an empty topic")

    facts = [
        str(f).strip()
        for f in data.get("key_facts", [])
        if str(f).strip()
    ][:MAX_KEY_FACTS]

    return TopicAssignment(topic=topic, key_facts=tuple(facts))


def _format_existing(topics: list[str]) -> str:
    if not topics:
        return "No topics exist yet; propose the first one."
    return "TOPICS ALREADY IN USE:\n" + "\n".join(f"- {t}" for t in topics)


class TopicExtractor:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def extract(
        self, query: str, summary: str, existing_topics: list[str]
    ) -> TopicAssignment:
        prompt = (
            f"{_format_existing(existing_topics)}\n\n"
            f"QUESTION: {query}\n\nANSWER: {summary}"
        )
        completion = self._llm.complete(SYSTEM_PROMPT, prompt, max_tokens=400)
        return parse_assignment(completion.text)
