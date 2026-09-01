"""Evaluation harness.

Two questions are asked of the system:

1. Retrieval - when a follow-up arrives, does memory surface the earlier
   entry it should, ahead of every unrelated entry?
2. Prediction - given a research trajectory with its final question
   removed, do the predicted next questions identify that question?

Prediction is scored as a discrimination task rather than against a
similarity cutoff. Each session's held-out question competes with the
held-out questions of every other session; a hit means the true question
ranked first. This avoids inventing a "close enough" threshold, which
would let the score be tuned after the fact.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

from chromadb.utils import embedding_functions

from mindtrail import config
from mindtrail.llm import LLMClient, LLMError
from mindtrail.memory.store import Entry, MemoryStore
from mindtrail.predict.next_query import NextQueryPredictor

EVAL_DIR = Path(__file__).parent


@dataclass(frozen=True)
class RetrievalOutcome:
    followup: str
    expected: str
    rank: int  # 1-indexed position of the expected entry, 0 if absent

    @property
    def hit_at_1(self) -> bool:
        return self.rank == 1

    @property
    def hit_at_3(self) -> bool:
        return 1 <= self.rank <= 3


@dataclass(frozen=True)
class PredictionOutcome:
    session_id: str
    true_next: str
    predictions: tuple[str, ...]
    is_hit: bool
    best_similarity: float
    tokens: int


def _cosine(a, b) -> float:
    """Cosine similarity, cast to a builtin float.

    The embedder returns numpy scalars, which json.dumps cannot serialize.
    """
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return float(dot / (na * nb)) if na and nb else 0.0


def load_json(name: str) -> dict:
    return json.loads((EVAL_DIR / name).read_text())


def run_retrieval_eval(tmp_path: Path) -> list[RetrievalOutcome]:
    """Load every stored entry into one store, then probe with follow-ups."""
    pairs = load_json("retrieval_pairs.json")["pairs"]
    store = MemoryStore(path=str(tmp_path / "retrieval"), collection="eval")

    for pair in pairs:
        store.add(pair["stored"], pair["summary"], [])

    outcomes = []
    for pair in pairs:
        found = store.search(pair["followup"], k=len(pairs))
        queries = [entry.query for entry in found]
        rank = queries.index(pair["stored"]) + 1 if pair["stored"] in queries else 0
        outcomes.append(
            RetrievalOutcome(
                followup=pair["followup"], expected=pair["stored"], rank=rank
            )
        )
    return outcomes


def _as_entries(questions: list[str]) -> list[Entry]:
    return [
        Entry(
            id=str(i),
            query=question,
            summary="",
            sources=(),
            created_at=f"2026-01-0{i + 1}T00:00:00+00:00",
        )
        for i, question in enumerate(questions)
    ]


def run_prediction_eval(llm: LLMClient, pause: float) -> list[PredictionOutcome]:
    sessions = load_json("sessions.json")["sessions"]
    embed = embedding_functions.DefaultEmbeddingFunction()
    predictor = NextQueryPredictor(llm)

    # Every session's held-out question is a candidate for every session,
    # so a lucky generic guess cannot score.
    candidates = [session["questions"][-1] for session in sessions]
    candidate_vectors = embed(candidates)

    outcomes = []
    for session in sessions:
        history, true_next = session["questions"][:-1], session["questions"][-1]

        predictions = predictor.predict(_as_entries(history))
        texts = [p.question for p in predictions]
        prediction_vectors = embed(texts)

        # Score each candidate by its best match against any prediction.
        scores = [
            max(_cosine(pv, cv) for pv in prediction_vectors)
            for cv in candidate_vectors
        ]
        winner = candidates[scores.index(max(scores))]
        true_score = scores[candidates.index(true_next)]

        outcomes.append(
            PredictionOutcome(
                session_id=session["id"],
                true_next=true_next,
                predictions=tuple(texts),
                is_hit=winner == true_next,
                best_similarity=true_score,
                tokens=0,
            )
        )
        time.sleep(pause)  # free tier is ~30 requests per minute
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the mindtrail evaluation.")
    parser.add_argument(
        "--skip-prediction",
        action="store_true",
        help="run only the offline retrieval eval (no API calls)",
    )
    parser.add_argument("--pause", type=float, default=2.5)
    parser.add_argument("--out", default="eval/results.json")
    args = parser.parse_args()

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        retrieval = run_retrieval_eval(Path(tmp))

    prediction: list[PredictionOutcome] = []
    if not args.skip_prediction:
        try:
            prediction = run_prediction_eval(
                LLMClient(temperature=config.EVAL_TEMPERATURE), args.pause
            )
        except LLMError as exc:
            print(f"prediction eval skipped: {exc}")

    from eval.report import render, to_dict

    print(render(retrieval, prediction))
    Path(args.out).write_text(json.dumps(to_dict(retrieval, prediction), indent=2))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
