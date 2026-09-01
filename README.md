# mindtrail

A research assistant that remembers. Ask it a question, and it searches the
web, synthesizes a sourced answer, and stores that answer in a searchable
memory. Every later question is answered *with* what it already learned, and
it can predict what you will want to know next.

```
$ mindtrail ask "what is a vector database"
$ mindtrail ask "how does Chroma differ from Pinecone"

Q: how does Chroma differ from Pinecone
--------------------------------------------------------------------
Chroma and Pinecone are two of the most-cited vector stores, but they take
opposite approaches to architecture and target use-cases...

Built on earlier research:
  - what is a vector database

Sources:
  [1] https://www.trychroma.com/
  [2] https://www.pinecone.io/learn/vector-database/
```

The second question was never told about the first. Memory surfaced it.

## Why this exists

Most "research agent" demos are stateless: every question starts from
nothing. The interesting problem is what happens on question five, when the
system should already know what you have been reading about. That means
three things have to work together — retrieval that finds the relevant past
entry, a prompt that composes it into context, and some model of where your
curiosity is heading.

## Results

Run with `python -m eval.runner`. Numbers below are from
`eval/results.json`, reproducible at temperature 0.

Both evals are deliberately harder than the versions they replaced. Each
started out reporting a flattering number that turned out to be measuring
something easier than the task, and the corrections are documented inline
rather than quietly folded in — the reasoning is the part worth reading.

The short version: retrieval works, prediction does not.

**Retrieval** — ten follow-up questions probe a memory holding all ten prior
entries, so every unrelated entry acts as a distractor. Scored on the test
split; a separate dev split exists for tuning.

| metric | score |
|---|---|
| recall@1 | 7/10 (70%) |
| recall@3 | 7/10 (70%) |

recall@3 equalling recall@1 is the interesting part: when retrieval misses,
it misses badly rather than narrowly. The three failures rank the correct
entry 4th, 6th, and 10th. So the fix is not reranking a near-miss — the
right entry is nowhere near the top, and something about those probes
(`how does Chroma differ from Pinecone` finding its parent entry at rank 10)
is genuinely not captured by the embedding.

An earlier version of this eval reported 50% recall@1 on eight pairs with
one-line summaries. That number was mostly an artifact of the fixture: real
syntheses run to a couple of paragraphs, and embedding a realistic summary
retrieves substantially better. The eval was measuring its own stub data.

I also tested whether embedding query and summary separately beats
concatenating them. It does not — see `eval/strategy_comparison.py`. On
eight pairs summary-only appeared to win by one case; on twenty split into
dev and test, every strategy except query-only is indistinguishable. The
concatenated default stands, now for a measured reason rather than an
assumed one.

**Prediction** — each session's final question is held out. The three
predicted questions are scored against a pool of 24 candidates: all six
held-out questions plus three plausible same-topic decoys per session. A hit
requires the true question to outrank all 23 others. Framing it as
discrimination avoids inventing a "close enough" similarity cutoff that
could be tuned after seeing the results.

| metric | score |
|---|---|
| exact question identified | 1.1/6 mean over 7 runs (range 1–2) |
| naive baseline, echo the trajectory | 1/6 (17%) |
| mean similarity to true next question | 0.37 |

**The prediction feature does not beat its baseline. That is the result.**

Getting there took two corrections, both worth stating because the
intermediate numbers looked good and were not.

*First*, this eval reported **83%**. With only the six held-out questions
competing, each from a different domain, any on-topic guess won — it was
measuring topic classification, not next-question prediction. Adding three
same-topic decoys per session widened the pool from 6 to 24 and dropped the
score to 2/6. The failures became legible too: the transformer session lost
to a decoy that paraphrases its own prediction, exactly the discrimination
the easy pool could never test.

*Second*, that 2/6 was a single run, and single runs are not stable here.
Repeating the identical eval gave 1, 2, 1, 1, 1, 1, 1 across seven runs —
**at temperature 0**. Pinning temperature fixed the wild swings seen at the
default, but Groq's hosted models are still not bit-reproducible, so any
single-run figure on n=6 is noise dressed as a measurement. `--trials N`
exists for this reason and the reported number is a mean.

A mean of ~1.1/6 against a baseline of 1/6 is no improvement. Reading the
predictions, they are consistently *sensible* and consistently *not the
specific question asked next* — plausible-next-question and
actual-next-question are different targets, and a research trajectory of
three questions is thin evidence for the second. Making this work would
likely need real usage signal, not better prompting.

### What these numbers do not say

- **n is small.** Six sessions and eight retrieval pairs. Each session is
  worth 17 points, so a single flip is visually dramatic and statistically
  meaningless.
- **The eval set is hand-authored, not recorded.** The trajectories are
  plausible research paths, not logs of real usage, so they are cleaner and
  more coherent than genuine browsing would be. Decoys were written by the
  same hand as the answers, which is its own bias.
- **Temperature 0 is necessary but not sufficient.** At the default it swung
  4/6 then 3/6; pinned at 0 it still ranges 1–2/6. Hosted inference is not
  bit-reproducible, so prediction numbers are only meaningful as a mean over
  trials.
- **The prompt was frozen before the decoy pool existed**, but temperature
  was changed after seeing results on this same set. With n=6 that is enough
  to matter; a separate dev set for tuning would be the honest fix.
- **One embedding model gates both numbers.** Retrieval and prediction
  scoring share Chroma's MiniLM, so its quirks shape both results.

## How it works

```
mindtrail ask "question"
        |
        v
  MemoryStore.search()  -> related past entries         (local embeddings)
        |
        v
  search + fetch        -> top pages, stripped to text  (DuckDuckGo)
        |
        v
  LLMClient.complete()  -> synthesis with citations     (Groq)
        |
        v
  MemoryStore.add()     -> persisted for next time
```

| module | responsibility |
|---|---|
| `mindtrail/memory/store.py` | Chroma-backed store; add, semantic search, recency |
| `mindtrail/ingest/search.py` | Search behind a provider protocol with fallback |
| `mindtrail/ingest/fetch.py` | URL to readable text, stdlib only |
| `mindtrail/ingest/researcher.py` | Retrieve, compose context, synthesize |
| `mindtrail/predict/next_query.py` | Three ranked next-question candidates |
| `mindtrail/llm.py` | Groq client with rate-limit backoff |
| `eval/` | Retrieval and prediction harness |

## Design decisions worth explaining

**Embeddings run locally.** Chroma bundles an ONNX MiniLM, so retrieval
needs no API key and costs nothing. This also avoids pulling in torch, which
would have added roughly 4GB for a job an 80MB model does.

**Search sits behind a protocol.** DuckDuckGo is scraped rather than served
by an official API, and it rate-limits without warning. `FallbackSearch`
takes an ordered list of providers so a second one can be added without the
researcher knowing.

**Retries are load-bearing.** The Groq free tier allows about 30 requests
and 12K tokens per minute. A single research query costs roughly 3,800
tokens, so about three questions per minute is the ceiling and a long eval
sweep *will* hit 429. Exponential backoff is why the harness finishes.

**Prediction returns three candidates, not one.** A single guess forces a
similarity threshold at eval time. A ranked list supports recall-style
scoring, which needs no arbitrary number.

**Untrusted URLs are scheme-checked before fetching.** Search results are
external input, and `urllib.request.urlopen` will happily serve `file://`.
It also raises `ValueError` rather than `URLError` for a scheme-less URL,
which used to abort an entire question instead of skipping one dead link.

## Setup

Requires Python 3.11+. Verified on 3.14.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env      # then add your Groq API key
```

A Groq key is free at [console.groq.com](https://console.groq.com) — no card
required. The model is `openai/gpt-oss-120b`; note that Groq removed the
Llama line from its catalog, so older tutorials naming
`llama-3.3-70b-versatile` will 404.

```bash
.venv/bin/python -m mindtrail.cli ask "what is a vector database"
.venv/bin/python -m mindtrail.cli search "vector"     # memory only, no lookups
.venv/bin/python -m mindtrail.cli predict             # likely next questions
.venv/bin/python -m mindtrail.cli stats               # what is remembered
```

## Tests

68 tests, no network and no API key required — search, fetch, and the model
are all stubbed. Coverage concentrates on logic that can be silently wrong
(retrieval ranking, JSON parsing, cosine math, retry backoff) rather than on
CLI glue.

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m eval.runner --skip-prediction   # offline half of the eval
.venv/bin/python -m eval.strategy_comparison        # retrieval strategy experiment
```

## Known limitations

- Retrieval fails outright rather than narrowly on 3 of 10 probes, and
  changing what gets embedded does not fix it (see above).
- Prediction does not beat a naive baseline once same-topic decoys are in
  play. Trajectory alone is thin signal for a *specific* next question, even
  when the topic is obvious. `predict` is still useful to a human as
  suggestions; it is just not validated as prediction.
- The eval set is synthetic; recording real sessions would be a truer test.
- Search depends on scraping DuckDuckGo, which will break periodically. The
  provider protocol exists so a replacement is a small change, but only one
  provider is implemented today.
- No deduplication: asking the same question twice stores two entries.
