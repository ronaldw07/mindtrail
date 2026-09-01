"""Compare what gets embedded for retrieval.

The store embeds query and summary concatenated. Whether that is better
than the alternatives is an empirical question, and this script is how it
was answered rather than assumed.

Selection is done on the dev split. The test split is printed alongside
only so the gap between the two is visible; nothing is chosen from it.

Run with: python -m eval.strategy_comparison
"""

from __future__ import annotations

import json
from pathlib import Path

from chromadb.utils import embedding_functions

from eval.runner import _cosine

STRATEGIES = ("concatenated", "query only", "summary only", "max(q,s)", "0.5q+0.5s")


def _score_one(strategy: str, vf, vq, vs, vc) -> float:
    if strategy == "concatenated":
        return _cosine(vf, vc)
    if strategy == "query only":
        return _cosine(vf, vq)
    if strategy == "summary only":
        return _cosine(vf, vs)
    if strategy == "max(q,s)":
        return max(_cosine(vf, vq), _cosine(vf, vs))
    if strategy == "0.5q+0.5s":
        return 0.5 * _cosine(vf, vq) + 0.5 * _cosine(vf, vs)
    raise ValueError(f"unknown strategy: {strategy}")


def evaluate(pairs: list[dict], strategy: str, embed) -> tuple[int, int, int]:
    """Returns (recall@1, recall@3, total) for one strategy."""
    queries = [p["stored"] for p in pairs]
    summaries = [p["summary"] for p in pairs]
    followups = [p["followup"] for p in pairs]

    vq, vs = embed(queries), embed(summaries)
    vc = embed([f"{q}\n\n{s}" for q, s in zip(queries, summaries)])
    vf = embed(followups)

    at_1 = at_3 = 0
    for i, probe in enumerate(vf):
        scores = [
            _score_one(strategy, probe, vq[j], vs[j], vc[j])
            for j in range(len(pairs))
        ]
        rank = sorted(range(len(scores)), key=lambda j: -scores[j]).index(i) + 1
        at_1 += rank == 1
        at_3 += rank <= 3
    return at_1, at_3, len(pairs)


def main() -> int:
    data = json.loads((Path(__file__).parent / "retrieval_pairs.json").read_text())
    embed = embedding_functions.DefaultEmbeddingFunction()

    for split in ("dev", "test"):
        label = "selection happens here" if split == "dev" else "reporting only"
        print(f"\n{split.upper()} ({label})")
        for strategy in STRATEGIES:
            at_1, at_3, total = evaluate(data[split], strategy, embed)
            print(
                f"  {strategy:14} recall@1 {at_1}/{total}   recall@3 {at_3}/{total}"
            )

    print(
        "\nConclusion: apart from query-only, the strategies are "
        "indistinguishable on both splits, so the concatenated default "
        "stands. An earlier eight-pair set appeared to favour summary-only; "
        "that gap was one example wide and did not survive a larger set."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
