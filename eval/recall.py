"""Retrieval recall on a shared corpus, with the numbers a reader can trust.

One store holds 90 research entries about CS and ML topics, many of them
close neighbours of each other (overfitting and regularization, TCP and
UDP, quicksort and merge sort). Each question must surface its entry
ahead of the other 89.

Two question sets: `tune` is for choosing between strategies, `heldout`
is scored once at the end. `--split heldout` refuses to run without
`--confirm-final`, so the held-out score can't drift into a tuning loop
by accident.

Reported: recall@1, @3, @5, mean reciprocal rank, a 95% Wilson interval
(a small test set can't support a bare percentage), and search latency.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from mindtrail.memory.store import MemoryStore

EVAL_DIR = Path(__file__).parent
PAIRS_FILE = EVAL_DIR / "recall_pairs.json"
RESULTS_FILE = EVAL_DIR / "recall_results.json"
SEARCH_DEPTH = 10  # how far down the ranking a hit still counts


def wilson_interval(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a proportion. (0, 0) for no trials."""
    if n == 0:
        return 0.0, 0.0
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def recall_at(ranks: list[int], k: int) -> float:
    """Share of questions whose entry came back in the top k (rank 0 = missed)."""
    return sum(1 for r in ranks if 1 <= r <= k) / len(ranks) if ranks else 0.0


def mean_reciprocal_rank(ranks: list[int]) -> float:
    return sum(1 / r for r in ranks if r >= 1) / len(ranks) if ranks else 0.0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1)]


def summarize(ranks: list[int], seconds: list[float]) -> dict:
    n = len(ranks)
    low, high = wilson_interval(sum(1 for r in ranks if r == 1), n)
    return {
        "questions": n,
        "recall@1": round(recall_at(ranks, 1), 3),
        "recall@1_ci95": [round(low, 3), round(high, 3)],
        "recall@3": round(recall_at(ranks, 3), 3),
        "recall@5": round(recall_at(ranks, 5), 3),
        "mrr": round(mean_reciprocal_rank(ranks), 3),
        "latency_p50_ms": round(percentile(seconds, 50) * 1000, 1),
        "latency_p95_ms": round(percentile(seconds, 95) * 1000, 1),
    }


# --- strategies: (store, question) -> ranked entries ----------------------------


def hybrid(store, question):
    return store.search(question, k=SEARCH_DEPTH)


def vector_only(store, question):
    return [e for e in (store.get(i) for i in store._vector_search_ids(question, SEARCH_DEPTH * 4))
            if e is not None][:SEARCH_DEPTH]


def keyword_only(store, question):
    return [e for e in (store.get(i) for i in store._fts_search_ids(question, SEARCH_DEPTH * 4))
            if e is not None][:SEARCH_DEPTH]


STRATEGIES = {"hybrid": hybrid, "vector": vector_only, "keyword": keyword_only}


def build_store(tmp: Path, corpus: list[dict]) -> tuple[MemoryStore, dict]:
    store = MemoryStore(path=str(tmp / "chroma"), collection="recall_eval")
    ids_by_query = {}
    for item in corpus:
        store.add(item["stored"], item["summary"], [])
        ids_by_query[item["stored"]] = item["id"]
    return store, ids_by_query


def run_strategy(store, ids_by_query: dict, questions: list[dict], strategy) -> tuple[list[int], list[float], list[dict]]:
    ranks, seconds, misses = [], [], []
    for q in questions:
        started = time.perf_counter()
        found = strategy(store, q["followup"])
        seconds.append(time.perf_counter() - started)
        got = [ids_by_query.get(e.query) for e in found]
        rank = got.index(q["expects"]) + 1 if q["expects"] in got else 0
        ranks.append(rank)
        if rank != 1:
            misses.append({"followup": q["followup"], "expected": q["expects"], "rank": rank,
                           "top": got[:3]})
    return ranks, seconds, misses


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=EVAL_DIR, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retrieval recall on the shared corpus.")
    parser.add_argument("--split", choices=("tune", "heldout"), default="tune")
    parser.add_argument("--strategies", default="hybrid,vector,keyword")
    parser.add_argument("--confirm-final", action="store_true",
                        help="required for --split heldout: the held-out set is scored once, at the end")
    parser.add_argument("--out", default="")
    parser.add_argument("--show-misses", action="store_true")
    args = parser.parse_args(argv)
    if args.split == "heldout" and not args.confirm_final:
        parser.error("the held-out split is scored once; pass --confirm-final to do it")

    pairs = json.loads(PAIRS_FILE.read_text())
    questions = pairs[args.split]
    names = [s for s in args.strategies.split(",") if s]
    report = {"split": args.split, "commit": _git_commit(), "corpus_size": len(pairs["corpus"]),
              "strategies": {}}
    with tempfile.TemporaryDirectory() as tmp:
        store, ids_by_query = build_store(Path(tmp), pairs["corpus"])
        for name in names:
            ranks, seconds, misses = run_strategy(store, ids_by_query, questions, STRATEGIES[name])
            report["strategies"][name] = summarize(ranks, seconds)
            if args.show_misses:
                report["strategies"][name]["misses"] = misses
            s = report["strategies"][name]
            lo, hi = s["recall@1_ci95"]
            print(f"{name:9s} n={s['questions']}  recall@1 {s['recall@1']:.0%} (95% CI {lo:.0%}-{hi:.0%})  "
                  f"@3 {s['recall@3']:.0%}  @5 {s['recall@5']:.0%}  MRR {s['mrr']}  "
                  f"p50 {s['latency_p50_ms']}ms p95 {s['latency_p95_ms']}ms")
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
