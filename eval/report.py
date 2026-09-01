"""Render evaluation outcomes as text and as JSON."""

from __future__ import annotations


def _percent(count: int, total: int) -> str:
    return f"{(100 * count / total):.0f}%" if total else "n/a"


def _retrieval_section(outcomes) -> list[str]:
    if not outcomes:
        return ["Retrieval: not run"]

    total = len(outcomes)
    at_1 = sum(o.hit_at_1 for o in outcomes)
    at_3 = sum(o.hit_at_3 for o in outcomes)

    lines = [
        "RETRIEVAL",
        f"  recall@1  {at_1}/{total}  ({_percent(at_1, total)})",
        f"  recall@3  {at_3}/{total}  ({_percent(at_3, total)})",
        "",
    ]
    misses = [o for o in outcomes if not o.hit_at_1]
    if misses:
        lines.append("  ranked below first:")
        lines += [
            f"    '{o.followup}' -> expected '{o.expected}' at rank "
            f"{o.rank if o.rank else 'absent'}"
            for o in misses
        ]
        lines.append("")
    return lines


def _prediction_section(outcomes, baseline, trial_hits=()) -> list[str]:
    if not outcomes:
        return ["PREDICTION: not run"]

    total = len(outcomes)
    hits = sum(o.is_hit for o in outcomes)
    mean_similarity = sum(o.best_similarity for o in outcomes) / total

    lines = ["PREDICTION"]
    if len(trial_hits) > 1:
        mean_hits = sum(trial_hits) / len(trial_hits)
        lines.append(
            f"  exact question identified  {mean_hits:.1f}/{total} mean over "
            f"{len(trial_hits)} trials  (range {min(trial_hits)}-{max(trial_hits)})"
        )
    else:
        lines.append(
            f"  exact question identified  {hits}/{total}  ({_percent(hits, total)})"
        )
    if baseline:
        base_hits = sum(o.is_hit for o in baseline)
        lines.append(
            f"  naive baseline (echo history)  {base_hits}/{len(baseline)}  "
            f"({_percent(base_hits, len(baseline))})"
        )
    lines += [
        f"  mean similarity to true next question  {mean_similarity:.2f}",
        f"  sample size  {total} sessions (small; see README)",
        "",
    ]
    for outcome in outcomes:
        mark = "hit " if outcome.is_hit else "miss"
        lines.append(f"  [{mark}] {outcome.session_id}")
        lines.append(f"         actual:    {outcome.true_next}")
        lines.append(f"         predicted: {outcome.predictions[0]}")
        if not outcome.is_hit and outcome.top_rival:
            lines.append(f"         lost to:   {outcome.top_rival}")
    lines.append("")
    return lines


def render(retrieval, prediction, baseline=(), trial_hits=()) -> str:
    divider = "=" * 68
    lines = [divider, "mindtrail evaluation", divider, ""]
    lines += _retrieval_section(retrieval)
    lines += _prediction_section(prediction, baseline, trial_hits)
    return "\n".join(lines)


def to_dict(retrieval, prediction, baseline=(), trial_hits=()) -> dict:
    return {
        "retrieval": {
            "total": len(retrieval),
            "recall_at_1": sum(o.hit_at_1 for o in retrieval),
            "recall_at_3": sum(o.hit_at_3 for o in retrieval),
            "cases": [
                {"followup": o.followup, "expected": o.expected, "rank": o.rank}
                for o in retrieval
            ],
        },
        "prediction": {
            "total": len(prediction),
            "hits": sum(o.is_hit for o in prediction),
            "baseline_hits": sum(o.is_hit for o in baseline),
            "trial_hits": list(trial_hits),
            "cases": [
                {
                    "session": o.session_id,
                    "true_next": o.true_next,
                    "predictions": list(o.predictions),
                    "hit": bool(o.is_hit),
                    "similarity": round(o.best_similarity, 4),
                    "top_rival": o.top_rival,
                }
                for o in prediction
            ],
        },
    }
