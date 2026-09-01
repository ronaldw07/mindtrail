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


def _prediction_section(outcomes) -> list[str]:
    if not outcomes:
        return ["PREDICTION: not run"]

    total = len(outcomes)
    hits = sum(o.is_hit for o in outcomes)
    mean_similarity = sum(o.best_similarity for o in outcomes) / total

    lines = [
        "PREDICTION",
        f"  correct session identified  {hits}/{total}  ({_percent(hits, total)})",
        f"  mean similarity to true next question  {mean_similarity:.2f}",
        f"  sample size  {total} sessions (small; see README)",
        "",
    ]
    for outcome in outcomes:
        mark = "hit " if outcome.is_hit else "miss"
        lines.append(f"  [{mark}] {outcome.session_id}")
        lines.append(f"         actual:    {outcome.true_next}")
        lines.append(f"         predicted: {outcome.predictions[0]}")
    lines.append("")
    return lines


def render(retrieval, prediction) -> str:
    divider = "=" * 68
    lines = [divider, "mindtrail evaluation", divider, ""]
    lines += _retrieval_section(retrieval)
    lines += _prediction_section(prediction)
    return "\n".join(lines)


def to_dict(retrieval, prediction) -> dict:
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
            "cases": [
                {
                    "session": o.session_id,
                    "true_next": o.true_next,
                    "predictions": list(o.predictions),
                    "hit": bool(o.is_hit),
                    "similarity": round(o.best_similarity, 4),
                }
                for o in prediction
            ],
        },
    }
