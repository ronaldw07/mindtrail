"""Optional model-assisted retrieval on top of MemoryStore.search.

Two independent steps, each costing one model call per search:

- `expand_query` rewrites a question into a few other ways it might be
  asked, plus a short passage in the style of an answer. Searching all of
  them and fusing the rankings finds entries a differently-worded
  question would miss.
- `rerank` asks the model to put the top candidates in order of how well
  each answers the question.

Whether either is worth its latency is decided by eval/recall.py, not
assumed. Both fall back to the plain ranking if the model call fails.
"""

from __future__ import annotations

from mindtrail.advice.json_reply import extract_json_object
from mindtrail.llm import LLMClient, LLMError
from mindtrail.memory.store import RRF_K, Entry, MemoryStore, _reciprocal_rank_fusion

EXPAND_MAX_TOKENS = 1200
RERANK_MAX_TOKENS = 1500
MAX_REWRITES = 3
RERANK_POOL = 8
SUMMARY_CHARS = 280

EXPAND_SYSTEM = (
    "You help search a personal notebook of researched questions and answers. Given a "
    "question, write other ways the same information need could be phrased, using "
    "different words and the technical terms an answer would contain. Also write one "
    "short passage (two sentences) that an answer to it would contain.\n"
    'Respond with JSON only: {"rewrites": ["...", "..."], "passage": "..."} with at most '
    f"{MAX_REWRITES} rewrites."
)

RERANK_SYSTEM = (
    "You rank candidate notebook entries by how directly each one answers a question. "
    "Each candidate has a number, the question it was saved under, and a summary. "
    "Judge by what the summary actually says, not just by topic.\n"
    'Respond with JSON only: {"ranking": [3, 1, 2]} listing every candidate number, best first.'
)


def expand_query(llm: LLMClient, question: str) -> list[str]:
    """The question plus up to MAX_REWRITES rewordings and one answer-style
    passage. Just [question] if the model call fails."""
    try:
        data = extract_json_object(llm.complete(EXPAND_SYSTEM, question, max_tokens=EXPAND_MAX_TOKENS).text)
    except (LLMError, ValueError):
        return [question]
    rewrites = data.get("rewrites") if isinstance(data.get("rewrites"), list) else []
    extra = [str(r).strip() for r in rewrites[:MAX_REWRITES] if str(r).strip()]
    passage = str(data.get("passage", "")).strip()
    if passage:
        extra.append(passage)
    return [question] + [q for q in extra if q.lower() != question.lower()]


def search_expanded(
    store: MemoryStore, llm: LLMClient, question: str, k: int = 3,
    keyword_weight: float = 1.0, queries: list[str] | None = None,
) -> list[Entry]:
    """Search every phrasing, then fuse. `queries` lets a caller reuse an
    expansion it already has."""
    queries = queries or expand_query(llm, question)
    depth = max(1, k) * 4
    lists, weights = [], []
    for q in queries:
        lists += [store._vector_search_ids(q, depth), store._fts_search_ids(q, depth)]
        weights += [1.0, keyword_weight]
    found = []
    for entry_id in _reciprocal_rank_fusion(lists, weights):
        entry = store.get(entry_id)
        if entry is not None:
            found.append(entry)
        if len(found) >= k:
            break
    return found


def rerank(llm: LLMClient, question: str, entries: list[Entry], k: int | None = None) -> list[Entry]:
    """Reorder the first RERANK_POOL entries by the model's judgement; the
    rest keep their place after them. Unchanged if the model call fails."""
    pool, rest = entries[:RERANK_POOL], entries[RERANK_POOL:]
    if len(pool) < 2:
        return entries[:k] if k else entries
    listing = "\n".join(f"{i}. [{e.query}] {e.summary[:SUMMARY_CHARS]}" for i, e in enumerate(pool, 1))
    try:
        data = extract_json_object(
            llm.complete(RERANK_SYSTEM, f"QUESTION: {question}\n\nCANDIDATES:\n{listing}",
                         max_tokens=RERANK_MAX_TOKENS).text)
        order = [int(n) for n in data.get("ranking", [])]
    except (LLMError, ValueError, TypeError):
        return entries[:k] if k else entries
    seen, ranked = set(), []
    for n in order:
        if 1 <= n <= len(pool) and n not in seen:
            seen.add(n)
            ranked.append(pool[n - 1])
    ranked += [e for i, e in enumerate(pool, 1) if i not in seen]   # anything the model skipped
    out = ranked + rest
    return out[:k] if k else out


DEEP_KEYWORD_WEIGHT = 0.3


def deep_search(store: MemoryStore, llm: LLMClient, question: str, k: int = 3) -> list[Entry]:
    """Expand the question, search every phrasing with the keyword list
    down-weighted, then let the model re-rank the best candidates. Two
    model calls; plain `store.search` is the fast path for everything
    interactive. Any model failure degrades to ordinary ranking."""
    candidates = search_expanded(store, llm, question, k=max(k, RERANK_POOL),
                                 keyword_weight=DEEP_KEYWORD_WEIGHT)
    return rerank(llm, question, candidates, k=k)
