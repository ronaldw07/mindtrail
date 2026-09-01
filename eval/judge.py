"""LLM judge for prediction correctness.

Cosine similarity turned out to be the wrong instrument here. It rewards
topical proximity, and a researcher's own previous questions are maximally
proximate, so a baseline that simply echoes the trajectory outscored the
model without predicting anything. The judge is asked the question the
metric was supposed to answer: does any candidate ask substantially what
the researcher actually asked next?
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from mindtrail.llm import LLMClient

SYSTEM_PROMPT = (
    "You grade next-question predictions. You are given the question a "
    "researcher actually asked next, and up to three predicted questions.\n\n"
    "Mark a hit only if at least one prediction asks substantially the same "
    "thing as the actual question - same information need, same specificity. "
    "Being on the same topic is NOT enough. A prediction that is broader, "
    "narrower, or about a neighbouring concern is a miss.\n\n"
    'Respond with JSON only: {"hit": true|false, "which": <1-based index or '
    '0>, "reason": "one sentence"}'
)


@dataclass(frozen=True)
class Judgement:
    is_hit: bool
    matched_index: int
    reason: str


def parse_judgement(text: str) -> Judgement:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in judge output: {text[:200]}")

    data = json.loads(payload[start : end + 1])
    if "hit" not in data:
        raise ValueError("judge output missing 'hit'")

    return Judgement(
        is_hit=bool(data["hit"]),
        matched_index=int(data.get("which", 0) or 0),
        reason=str(data.get("reason", "")).strip(),
    )


def format_case(actual: str, predictions: list[str]) -> str:
    numbered = "\n".join(
        f"{i}. {p}" for i, p in enumerate(predictions, start=1)
    )
    return f"ACTUAL NEXT QUESTION:\n{actual}\n\nPREDICTIONS:\n{numbered}"


class PredictionJudge:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def judge(self, actual: str, predictions: list[str]) -> Judgement:
        if not predictions:
            return Judgement(is_hit=False, matched_index=0, reason="no predictions")

        completion = self._llm.complete(
            SYSTEM_PROMPT, format_case(actual, predictions), max_tokens=400
        )
        return parse_judgement(completion.text)
