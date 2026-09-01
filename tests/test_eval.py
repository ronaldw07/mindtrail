"""Eval scoring tests. Offline; no API key or network needed."""

import json
from pathlib import Path

import pytest

from eval.report import to_dict
from eval.runner import (
    PredictionOutcome,
    RetrievalOutcome,
    _cosine,
    build_candidate_pool,
    run_retrieval_eval,
)


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


def _pairs(split: str) -> list[dict]:
    return json.loads((Path("eval") / "retrieval_pairs.json").read_text())[split]


@pytest.mark.parametrize("split", ["dev", "test"])
def test_retrieval_eval_scores_every_pair(tmp_path, split):
    outcomes = run_retrieval_eval(tmp_path / split, split=split)

    assert len(outcomes) == len(_pairs(split))


def test_retrieval_eval_defaults_to_the_test_split(tmp_path):
    # Defaulting to dev would report a number tuned on its own data.
    assert len(run_retrieval_eval(tmp_path)) == len(_pairs("test"))


def test_dev_and_test_probes_do_not_overlap():
    dev = {p["followup"] for p in _pairs("dev")}
    test = {p["followup"] for p in _pairs("test")}

    assert not dev & test


def an_outcome(is_hit=True):
    return PredictionOutcome(
        session_id="s",
        true_next="q",
        predictions=("a",),
        is_hit=is_hit,
        best_similarity=0.5,
        top_rival="rival",
    )


def test_candidate_pool_has_no_duplicates():
    # Scoring resolves a candidate by value, so a duplicate would make one
    # session score against the wrong entry.
    sessions = json.loads((Path("eval") / "sessions.json").read_text())["sessions"]

    pool = build_candidate_pool(sessions)

    assert len(pool) == len(set(pool))


def test_report_is_json_serializable():
    retrieval = [RetrievalOutcome(followup="f", expected="e", rank=1)]

    # Raises TypeError if any numpy scalar leaked through.
    json.dumps(to_dict(retrieval, [an_outcome()], [an_outcome(is_hit=False)]))


def test_candidate_pool_includes_decoys_alongside_held_out_questions():
    sessions = json.loads((Path("eval") / "sessions.json").read_text())["sessions"]

    pool = build_candidate_pool(sessions)

    expected = sum(1 + len(s.get("decoys", [])) for s in sessions)
    assert len(pool) == expected


def test_every_held_out_question_is_in_the_pool():
    sessions = json.loads((Path("eval") / "sessions.json").read_text())["sessions"]

    pool = build_candidate_pool(sessions)

    assert all(s["questions"][-1] in pool for s in sessions)


def test_pool_is_harder_than_one_candidate_per_session():
    # Without decoys the task degrades into topic classification, which
    # any on-topic guess wins.
    sessions = json.loads((Path("eval") / "sessions.json").read_text())["sessions"]

    assert len(build_candidate_pool(sessions)) > len(sessions)


def test_baseline_hits_are_reported_separately():
    report = to_dict([], [an_outcome()], [an_outcome(is_hit=False)])

    assert report["prediction"]["hits"] == 1
    assert report["prediction"]["baseline_hits"] == 0
