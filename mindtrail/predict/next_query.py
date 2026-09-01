"""Predict what the user will want to know next.

Three candidates are produced rather than one. A single guess forces an
arbitrary "close enough" similarity threshold at eval time, whereas a
ranked list supports recall@3, which needs no magic number.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from mindtrail.llm import LLMClient
from mindtrail.memory.store import Entry, MemoryStore

PREDICTIONS_RETURNED = 3

SYSTEM_PROMPT = (
    "You predict a researcher's next question. You are given their recent "
    "trajectory: what they asked, and what each answer told them.\n\n"
    "Predict the specific question they ask NEXT, not a general summary of "
    "where the topic could go. Favour the concrete unresolved thing an "
    "answer raised over a broad survey question. A researcher who has just "
    "learned how something works usually asks about applying, sizing, "
    "choosing, or troubleshooting it next.\n\n"
    "Return exactly three distinct candidate questions, ordered most to "
    "least likely, phrased the way the researcher would type them. Respond "
    'with JSON only, in the form {"predictions": [{"question": "...", '
    '"reasoning": "..."}]} with no surrounding prose or code fences.'
)


@dataclass(frozen=True)
class Prediction:
    question: str
    reasoning: str


def _extract_json(text: str) -> dict:
    """Parse the model's JSON, tolerating code fences around it."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {text[:200]}")
    return json.loads(payload[start : end + 1])


def parse_predictions(text: str) -> list[Prediction]:
    data = _extract_json(text)
    raw = data.get("predictions", [])
    if not isinstance(raw, list):
        raise ValueError("'predictions' must be a list")

    predictions = [
        Prediction(
            question=str(item["question"]).strip(),
            reasoning=str(item.get("reasoning", "")).strip(),
        )
        for item in raw
        if isinstance(item, dict) and str(item.get("question", "")).strip()
    ]
    if not predictions:
        raise ValueError("model returned no usable predictions")
    return predictions[:PREDICTIONS_RETURNED]


SUMMARY_CHARS_IN_TRAJECTORY = 400


def format_trajectory(entries: list[Entry]) -> str:
    """Render entries oldest-first, which is how the prompt expects them.

    What was learned is included alongside each question. Predicting from
    question text alone leaves the model guessing about content it has
    already retrieved, and a follow-up is usually prompted by something
    an answer said rather than by the question that produced it.
    """
    ordered = sorted(entries, key=lambda e: e.created_at)

    lines: list[str] = []
    for i, entry in enumerate(ordered, start=1):
        lines.append(f"{i}. asked: {entry.query}")
        if entry.summary:
            learned = entry.summary[:SUMMARY_CHARS_IN_TRAJECTORY]
            lines.append(f"   learned: {learned}")
    return "\n".join(lines)


class NextQueryPredictor:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def predict(self, entries: list[Entry]) -> list[Prediction]:
        if not entries:
            raise ValueError("no research history to predict from")

        prompt = (
            "RECENT RESEARCH TRAJECTORY (oldest first):\n"
            f"{format_trajectory(entries)}\n\n"
            "What are the three most likely next questions?"
        )
        completion = self._llm.complete(SYSTEM_PROMPT, prompt, max_tokens=700)
        return parse_predictions(completion.text)


def predict_from_store(
    store: MemoryStore, llm: LLMClient, history: int = 5
) -> list[Prediction]:
    return NextQueryPredictor(llm).predict(store.recent(history))
