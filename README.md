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

**Retrieval** — eight follow-up questions probe a memory holding all eight
prior entries, so every unrelated entry acts as a distractor.

| metric | score |
|---|---|
| recall@1 | 4/8 (50%) |
| recall@3 | 6/8 (75%) |

recall@3 is the number that matters operationally, since the researcher
injects the top three memories into the prompt. recall@1 is weak, and
honestly so: the failures are all cases where two stored entries are
topically adjacent (`how does HNSW indexing work` losing to other vector
search entries). Concatenating query and summary into one embedding is the
likely cause; embedding them separately and scoring jointly is the obvious
next thing to try.

**Prediction** — each session's final question is held out. The three
predicted questions are scored against a pool of 24 candidates: all six
held-out questions plus three plausible same-topic decoys per session. A hit
requires the true question to outrank all 23 others. Framing it as
discrimination avoids inventing a "close enough" similarity cutoff that
could be tuned after seeing the results.

| metric | score |
|---|---|
| exact question identified | 2/6 (33%) |
| naive baseline, echo the trajectory | 1/6 (17%) |
| mean similarity to true next question | 0.38 |

**This number was 83% before the decoys existed, and that version was
wrong.** With only the six held-out questions competing, each from a
different domain, any on-topic guess won — the eval was measuring topic
classification, not next-question prediction. Adding same-topic decoys
dropped it to 33%. The failure modes are now legible: the
transformer-internals session lost to a decoy that paraphrases its own
prediction, which is precisely the discrimination the easy pool never
tested.

33% against a 17% baseline is a real but modest signal, and with n=6 that is
two hits against one. It should be read as "better than echoing history,"
not as a demonstrated capability.

### What these numbers do not say

- **n is small.** Six sessions and eight retrieval pairs. Each session is
  worth 17 points, so a single flip is visually dramatic and statistically
  meaningless.
- **The eval set is hand-authored, not recorded.** The trajectories are
  plausible research paths, not logs of real usage, so they are cleaner and
  more coherent than genuine browsing would be. Decoys were written by the
  same hand as the answers, which is its own bias.
- **Sampling made this unreportable at first.** At the default temperature,
  two runs over identical input scored 4/6 and then 3/6. Pinning temperature
  to 0 made runs reproducible. Any prediction number reported without a
  fixed temperature is noise.
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
```

## Known limitations

- Retrieval degrades when stored entries are topically adjacent (see above).
- Prediction is weak (33%) once same-topic decoys are in play. The honest
  reading is that trajectory alone is thin signal for a *specific* next
  question, even when the topic is obvious.
- The eval set is synthetic; recording real sessions would be a truer test.
- Search depends on scraping DuckDuckGo, which will break periodically. The
  provider protocol exists so a replacement is a small change, but only one
  provider is implemented today.
- No deduplication: asking the same question twice stores two entries.
