# mindtrail

A research assistant that remembers. Ask it a question, and it searches the
web, synthesizes a sourced answer, tags it with a topic, and stores it in a
searchable memory. Every later question is answered *with* what it already
learned, and you can browse everything it's learned as a topic-organized
page in your browser.

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

```
$ mindtrail web
```

Opens a single local page: every question grouped under its topic (assigned
automatically, existing topics reused rather than fragmented), key facts as
bullets, full answer behind a click, sources linked, and a keyword filter
across everything you've asked. No server, no login, nothing to keep
running — the command regenerates the file and opens it.

```
$ mindtrail chat
```

Opens a browser chat window at `localhost:8765`, landing on **Today** — a
dashboard pulling together each project's cached highlights, the roadmap
steps you've accepted but haven't finished, and your most recently touched
chats and documents. Nothing on it triggers a model call; it only reads
what's already stored, so opening it costs nothing. Click the mindtrail
logo any time to come back to it.

A search box sits at the top of the sidebar — semantic search over
everything stored (research, notes, documents), the same retrieval that
powers follow-up recall, now reachable directly instead of only through a
question. Results link straight into the conversation they came from.

The sidebar also holds **projects** you create by hand, with chats nested
under them:

- **Rename, delete, pin, and mark unread** any chat from its `⋯` menu.
  Pinned sorts to the top; unread shows bold with a dot.
- **Move chats between projects**, or out of one entirely. Deleting a
  project keeps its chats and unfiles them; deleting a *chat* does
  remove its content.
- **🎤 dictate** — records from your mic and transcribes with Whisper.
- **+ upload a PDF** into the open chat, parsed and stored as knowledge
  you can then ask about.

Clicking a project name opens its own screen, with three things beside
its chats:

- **What's next** — three to five concrete actions drawn from that
  project's chats and files, each citing what it came from. Regenerates
  when the project has actually moved on, so opening an unchanged
  project costs nothing and renders from cache.
- **Instructions** — free text applied to every answer in that project.
  Writing "cite only primary sources" there changes the research, rather
  than being a note to yourself.
- **Roadmap** — a goal broken into a draggable node canvas. Generating
  proposes steps with dependencies between them; accept, reject, note, or
  drag any node, and regenerating only ever touches the still-proposed
  ones, planning around whatever you already decided. A chat panel sits
  alongside the canvas — ask about the plan or tell it what changed, and
  it can propose adding a step, changing a status, or attaching a note.
  It never applies anything itself; every proposal shows up as a card you
  accept or dismiss.
- **Files** — documents uploaded into that project.
- **Project Assistant** — the same propose/accept pattern as the roadmap
  chat, scoped to this project: ask it to rename the project or change its
  instructions, and it proposes the change as a card rather than doing it.

Follow-ups within a chat carry that conversation's earlier turns, so
"what are its drawbacks?" resolves against what you were just discussing
rather than being searched literally.

**👤 Profile**, in the sidebar, is a short freeform description of you —
role, goals, background — used to personalize every answer, highlight, and
roadmap. Write it by hand, generate a starting draft from whatever
documents are already stored, or talk it through with the **Profile
Assistant**, which proposes a full replacement text for you to accept.

Every chat assistant in the app (roadmap, project, profile) shares the
same safety property: the model only ever proposes a structured action,
shown as a card with Accept/Dismiss. Nothing is written until you click
Accept, and accepting always goes through the exact same endpoint a
manual edit would use — a chat-driven change and a hand-typed one are
indistinguishable to the server.

Existing research from before projects existed is migrated automatically
on first run: one conversation per topic, nothing orphaned.

```
$ mindtrail docs resume.pdf
$ mindtrail note "targeting agent/eval-focused AI internships for 2026"
$ mindtrail advice
```

Upload a PDF or jot a note and it's stored, topic-labeled, and searchable
exactly like research — a follow-up question in `ask` or `chat` can recall
your resume or a note the same way it recalls a prior answer. `advice`
reads everything stored (documents, notes, research) and writes a
prioritized plan, citing which document/note/topic each recommendation
comes from. `web` pins the latest advice above the topic sections. The
browser has its own **+ Note** button in the sidebar, next to Profile — the
CLI command above stores a note with no conversation attached, which used
to mean it was invisible in the browser; both paths now always attach one.

Photos and scanned documents aren't supported — there's no vision-capable
model on this Groq account (verified directly against the API, not
assumed), so only typed-text PDFs extract.

Prediction (guessing your next question) also exists but is **not** a
working feature — see [Results](#results) for why it's reported as a
negative finding rather than something to rely on.

## Why this exists

Most "research agent" demos are stateless: every question starts from
nothing. The interesting problem is what happens on question five, when the
system should already know what you have been reading about, and when you
want to look back at everything without re-asking it. That needs retrieval
that finds the relevant past entry, a prompt that composes it into context,
and a way to browse what's accumulated that isn't just a flat log of
questions in the order you happened to ask them — hence grouping by topic.

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
| exact question identified (dev, tuning set) | 2.5/7 mean, vs. 0/7 baseline |
| exact question identified (test, held out) | 0.5/7, single measurement |
| mean similarity to true next question | 0.33 |

**The prediction feature does not work, and the path to that conclusion is
the more interesting part.**

Three corrections got here, each because a number looked good and wasn't.

*First*, the eval reported 83%. With only six held-out questions competing,
each from a different domain, any on-topic guess won — it measured topic
classification. Adding three same-topic decoys per session (pool 6 → 24)
dropped it to 2/6, and the failures became legible: predictions lost to
decoys that paraphrase them.

*Second*, at temperature 0 that 2/6 still ranged 1–2 across seven repeats —
Groq's hosted models are not bit-reproducible even pinned. `--trials`
reports a mean rather than a single run.

*Third*, and the one that mattered most: **the metric itself was wrong.** A
baseline that just echoes the researcher's own prior questions was scoring
0.57 by cosine similarity — higher than the model — because a person's past
question is maximally on-topic with their next one, and cosine rewards
topical closeness, not correctness. The scorer could not tell "predicted
right" from "in the right neighbourhood." Replaced it with an LLM judge
(`eval/judge.py`) asked directly: does any candidate ask *substantially the
same thing* as what was actually asked next? Under that judge the echo
baseline correctly drops to 0/7 — echoing is never literally the next
question — and the metric finally measures the right thing.

Once the predictor could also see what each answer taught it (not just the
question text — `format_trajectory` used to discard summaries entirely),
dev split scored **2.5/7 against a 0/7 baseline**, a real if modest lift.
That result did not replicate on the held-out test split, which scored
**0.5/7 with the identical frozen config** — one hit across seven sessions
in the trials that completed before the day's Groq token quota was
exhausted mid-sweep. The judge's own reasoning for each miss is consistent
and specific: predictions stay on-topic but land on the wrong facet of it
(architecture instead of benchmarking, tuning instead of application, and
so on).

Reading dev and test side by side, dev's lift over baseline is thin enough
(2.5 out of 7, only 3 dev sessions) that it may not have been real signal
to begin with — seven sessions is not enough to distinguish "the technique
works" from "the small sample happened to land that way." Test is the
number to trust, and it says three prior questions plus their answers is
not enough evidence to name what someone asks next. That is a legitimate
negative result about trajectory-only prediction, not a bug to chase.

### What these numbers do not say

- **n is small.** Six sessions and eight retrieval pairs. Each session is
  worth 17 points, so a single flip is visually dramatic and statistically
  meaningless.
- **The eval set is hand-authored, not recorded.** The trajectories are
  plausible research paths, not logs of real usage, so they are cleaner and
  more coherent than genuine browsing would be. Decoys were written by the
  same hand as the answers, which is its own bias.
- **Temperature 0 is necessary but not sufficient.** At the default it swung
  4/6 then 3/6; pinned at 0 it still ranges 1–2/6 on repeats. Hosted
  inference is not bit-reproducible, so prediction numbers are only
  meaningful as a mean over trials.
- **The test number is a single measurement, not a mean.** Groq's daily
  token quota was exhausted mid-sweep, which the harness handled cleanly
  (partial results are kept, per the eval-resilience fix below) but which
  also means test wasn't averaged over multiple trials the way dev was.
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
  MemoryStore.search()   -> related past entries         (local embeddings)
        |
        v
  search + fetch         -> top pages, stripped to text  (DuckDuckGo)
        |
        v
  LLMClient.complete()   -> synthesis with citations     (Groq)
        |
        v
  TopicExtractor.extract() -> topic label + key facts    (Groq, reuses
        |                                                 existing labels)
        v
  MemoryStore.add()      -> persisted for next time

mindtrail web
        |
        v
  MemoryStore.all()  ->  build_html()  ->  static file, opened in browser
                          (grouped by topic, keyword filter, no server)
```

| module | responsibility |
|---|---|
| `mindtrail/memory/store.py` | Chroma-backed store; add, semantic search, recency, topics |
| `mindtrail/ingest/search.py` | Search behind a provider protocol with fallback |
| `mindtrail/ingest/fetch.py` | URL to readable text, stdlib only |
| `mindtrail/ingest/researcher.py` | Retrieve, compose context, synthesize |
| `mindtrail/ingest/topic.py` | Topic label + key-fact extraction, reusing existing labels |
| `mindtrail/web/generate.py` | Static HTML page grouped by topic |
| `mindtrail/web/chat_server.py` | HTTP routing only, stdlib http.server, no framework |
| `mindtrail/web/api.py` | Request handlers as pure functions over the stores |
| `mindtrail/web/chat_ui.py` | Chat page markup, styles, and client script |
| `mindtrail/organize/` | Projects and conversations in SQLite, plus the backfill |
| `mindtrail/organize/profile.py` | The user's own background: single-row store, edit-and-save |
| `mindtrail/organize/roadmaps.py` | Roadmaps and nodes: CRUD, status, notes, canvas position |
| `mindtrail/ingest/documents.py` | PDF text extraction, local, no vision model available |
| `mindtrail/advice/planner.py` | Grounded next-steps plan across everything stored |
| `mindtrail/advice/highlights.py` | Per-project "what's next", cached with staleness detection |
| `mindtrail/advice/profile_draft.py` | Draft a starting profile from stored documents and notes |
| `mindtrail/advice/roadmap_gen.py` | Propose roadmap steps toward a goal, preserving decided nodes |
| `mindtrail/advice/roadmap_chat.py` | Conversational roadmap assistant - proposes actions, never applies them |
| `mindtrail/advice/project_chat.py` | Conversational project assistant - proposes rename/instructions changes |
| `mindtrail/advice/profile_chat.py` | Conversational profile assistant - proposes a full replacement to accept |
| `mindtrail/predict/next_query.py` | Three ranked next-question candidates (not validated — see Results) |
| `mindtrail/llm.py` | Groq client with rate-limit backoff |
| `eval/` | Retrieval and prediction harness, plus the LLM judge |

## Design decisions worth explaining

**Embeddings run locally.** Chroma bundles an ONNX MiniLM, so retrieval
needs no API key and costs nothing. This also avoids pulling in torch, which
would have added roughly 4GB for a job an 80MB model does.

**Entries are chunked before embedding.** That MiniLM truncates at 256
word-piece tokens with no warning — anything past roughly 800 characters was
silently invisible to search. Measured against this project's own stored
entries, 13 of 19 exceeded it; long research summaries and uploaded PDFs
were the worst hit. `store.add` now splits long text into ~800-char chunks
on sentence boundaries, embeds each separately, and `store.search` collapses
multiple chunk hits back to one result per entry. A one-time
`reindex_legacy_entries()` runs at `chat` startup so entries written before
this existed get migrated in place, keeping their original id. This did not
move the reported recall@1/@3 below — the eval fixture's summaries max out
around 365 characters and never approached the truncation point, so it
exercises a different failure mode than the one this fixes.

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

**Prediction is judged, not scored by cosine similarity.** Similarity gave
a baseline that echoes prior questions a higher score than the model,
because a person's own past questions are the most topically-similar thing
to their next one. Correctness and topical proximity are different axes;
only a judge that reads the actual content can tell them apart.

**The predictor sees what it learned, not just what it asked.**
`format_trajectory` used to render question text only. Follow-up questions
are usually prompted by something an *answer* said, not by the question
that produced it, so withholding the summaries was withholding the signal
most likely to matter.

**Topics are reused, not reinvented per question.** `TopicExtractor` is
shown every topic label already in the store and told to reuse one if it
genuinely fits. Without that, near-identical topics ("Vector Databases",
"Vector Search", "Vector DBs") would accumulate and the topic-grouped view
would fragment into noise instead of staying navigable. Labeling runs after
the answer is written and never blocks storing it — a failed extraction
still keeps the research, just uncategorized.

**Organizational state lives in SQLite, not Chroma.** Chroma is a vector
index; renaming a project should not touch embeddings, and an empty
project has nowhere to live there at all. SQLite is stdlib, handles the
threaded server's concurrent writes, and makes move/pin/delete one-line
updates. Deleting a project unfiles its chats via `ON DELETE SET NULL`
rather than destroying research — foreign keys are enabled per
connection, since SQLite defaults them off and would silently orphan
rows instead.

**Documents are parsed locally, not sent to a vision model.** A vision
model was the first plan; a direct test against this Groq account's
`gpt-oss-120b` with an `image_url` message returned a plain 400
("content must be a string"), and the account has no vision-capable model
at all. `pypdf` extracts typed text for free instead — it won't read
scans or photos, but it needed no new API surface and no cost.

**Advice reads memory once, it doesn't call out to a fresh researcher
run.** `mindtrail advice` is one completion over whatever's already
stored, which keeps it cheap and means every recommendation is
traceable to a specific document, note, or research entry rather than
new information invented on the spot.

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
.venv/bin/python -m mindtrail.cli web                 # static page, grouped by topic
.venv/bin/python -m mindtrail.cli chat                 # browser chatbot interface
.venv/bin/python -m mindtrail.cli docs resume.pdf       # parse and store a PDF
.venv/bin/python -m mindtrail.cli note "some note"      # save a manual note
.venv/bin/python -m mindtrail.cli advice                # generate a next-steps plan
```

`web` writes a single HTML file and opens it in your default browser. Each
`ask` assigns a topic label (reusing an existing one when it fits) and 3-5
key facts; the page groups entries under those topics with a keyword filter
and links back to sources. Nothing to keep running — regenerate with `web`
whenever you want it current.

## Tests

425 tests, no network and no API key required — search, fetch, and the model
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
- Prediction does not replicate on held-out data: a real lift over baseline
  on the tuning split (2.5/7) fell to 0.5/7 on test. Three prior questions
  and their summaries are thin evidence for the *specific* next question,
  even when the general direction is obvious to a human reader. `predict`
  is still useful to a person as suggestions; it is not validated as
  prediction.
- Groq's free tier has a 200K token/day cap in addition to the per-minute
  limit. A long eval sweep can exhaust it mid-run; the harness records
  whatever completed rather than losing the sweep, but the run should be
  read as partial when that happens.
- The eval set is synthetic; recording real sessions would be a truer test.
- Search depends on scraping DuckDuckGo, which will break periodically. The
  provider protocol exists so a replacement is a small change, but only one
  provider is implemented today.
- No deduplication: asking the same question twice stores two entries,
  which can also land in two different (if similarly-named) topic sections
  on the generated page, since topic reuse depends on the model recognizing
  the overlap rather than exact matching.
- Entries stored before topic labeling existed have no topic and appear
  under Uncategorized on `mindtrail web` until re-asked.
