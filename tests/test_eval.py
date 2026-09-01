"""Eval scoring tests. Offline; no API key or network needed."""

import json
from pathlib import Path

import pytest

from eval.report import to_dict
from eval.runner import PredictionOutcome, RetrievalOutcome, _cosine, run_retrieval_eval


def test_cosine_of_identical_vectors_is_one():
    assert _cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_of_orthogonal_vectors_is_zero():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_ignores_magnitude():
    assert _cosine([1.0, 1.0], [5.0, 5.0]) == pytest.approx(1.0)


def test_cosine_of_a_zero_vector_is_zero():
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_returns_a_builtin_float():
    # numpy scalars break json.dumps, so the cast is load-bearing.
    assert type(_cosine([1.0, 2.0], [2.0, 1.0])) is float


def test_rank_one_counts_for_both_recall_levels():
    outcome = RetrievalOutcome(followup="f", expected="e", rank=1)

    assert outcome.hit_at_1 and outcome.hit_at_3


def test_rank_three_counts_only_at_three():
    outcome = RetrievalOutcome(followup="f", expected="e", rank=3)

    assert not outcome.hit_at_1
    assert outcome.hit_at_3


def test_absent_entry_counts_for_neither():
    outcome = RetrievalOutcome(followup="f", expected="e", rank=0)

    assert not outcome.hit_at_1
    assert not outcome.hit_at_3


def test_retrieval_eval_scores_every_pair(tmp_path):
    outcomes = run_retrieval_eval(tmp_path)

    pairs = json.loads(
        (Path("eval") / "retrieval_pairs.json").read_text()
    )["pairs"]
    assert len(outcomes) == len(pairs)


def test_report_is_json_serializable():
    retrieval = [RetrievalOutcome(followup="f", expected="e", rank=1)]
    prediction = [
        PredictionOutcome(
            session_id="s",
            true_next="q",
            predictions=("a",),
            is_hit=True,
            best_similarity=0.5,
            tokens=0,
        )
    ]

    # Raises TypeError if any numpy scalar leaked through.
    json.dumps(to_dict(retrieval, prediction))
