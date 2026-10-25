"""The recall eval's maths and its guard on the held-out split."""

import json

import pytest

from eval import recall


def test_wilson_interval_brackets_the_proportion_and_narrows_with_more_data():
    lo, hi = recall.wilson_interval(8, 10)
    assert lo < 0.8 < hi and 0.45 < lo < 0.55 and 0.9 < hi < 0.97   # the "8/10" problem
    lo2, hi2 = recall.wilson_interval(80, 100)
    assert (hi2 - lo2) < (hi - lo)
    assert recall.wilson_interval(0, 0) == (0.0, 0.0)
    assert recall.wilson_interval(10, 10)[1] == 1.0


def test_metrics_on_known_ranks():
    ranks = [1, 1, 2, 0, 5]            # rank 0 = never returned
    assert recall.recall_at(ranks, 1) == 0.4
    assert recall.recall_at(ranks, 3) == 0.6
    assert recall.recall_at(ranks, 5) == 0.8
    assert recall.mean_reciprocal_rank(ranks) == pytest.approx((1 + 1 + 0.5 + 0 + 0.2) / 5)
    assert recall.recall_at([], 1) == 0.0 and recall.mean_reciprocal_rank([]) == 0.0


def test_percentile_picks_a_real_observation():
    values = [0.01, 0.02, 0.03, 0.04, 0.10]
    assert recall.percentile(values, 50) == 0.03 and recall.percentile(values, 95) == 0.10


def test_held_out_split_refuses_to_run_without_the_flag(capsys):
    with pytest.raises(SystemExit):
        recall.main(["--split", "heldout"])
    assert "confirm-final" in capsys.readouterr().err


def test_the_question_file_is_well_formed():
    pairs = json.loads(recall.PAIRS_FILE.read_text())
    ids = {c["id"] for c in pairs["corpus"]}
    assert len(ids) == len(pairs["corpus"]) == 90
    queries = [c["stored"] for c in pairs["corpus"]]
    assert len(set(queries)) == len(queries)           # ranks are looked up by stored question
    for split in ("tune", "heldout"):
        assert len(pairs[split]) == 45
        assert all(q["expects"] in ids for q in pairs[split])
    assert not {q["expects"] for q in pairs["tune"]} & {q["expects"] for q in pairs["heldout"]}
