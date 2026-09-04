# mindtrail — macOS chrome + power-user features

Revised after an audit that falsified several claims in the first draft. Corrections are
marked ✗ where the original was wrong, so nobody re-derives the mistake.

Baseline: `30ece95` on `main`, 462 tests passing, tree clean.
`chat_ui.py` is **3,008 lines** (✗ first draft said 2,942).

Locked decisions — do not relitigate:

- **macOS *app* chrome**, not apple.com marketing. Dense, tool-shaped, vibrancy, hairlines.
- **Dark only.** The 42 tokens from `731c2b0` carry over.
- Motion follows the Emil Kowalski framework. The binding rule: **never animate
  keyboard-initiated actions**, so the command palette has no open/close animation.

---

## Phase 0 — Extract the frontend to real static files

✗ The first draft proposed splitting the Python string into ~12 modules to unlock
parallelism. That justification is false: all 2,392 script lines live in **one `<script>`
tag sharing one scope** (`roadmapView` declared at 633 is read at 2100+; `toast` at 808 is
called from everywhere). Concatenating fragments preserves that scope exactly — it buys
git-merge isolation, not correctness isolation.

**Do this instead:** real files.

```
mindtrail/web/static/app.css     ← the <style> block
mindtrail/web/static/app.js      ← the <script> block
```

`chat_ui.py` keeps `CHAT_HTML` as shell markup only. `chat_server.py` gains two
`/static/...` branches reading from `Path(__file__).parent`, served with
**`Cache-Control: no-store`** — otherwise Phase 2 gets debugged against a stale `app.js`.

Why this wins: `node --check` and editor language services work natively, a CSS linter
becomes possible, and it's a real boundary. The feared costs evaporated on inspection —
the Dockerfile's `COPY mindtrail/ mindtrail/` already picks up the new directory, there is
no `pyproject.toml` or `package_data` to update, and exactly five test assertions break
(`test_chat_server.py:698, 706, 710-712, 717-718`), fixed by a three-line helper.

**Verification gate: byte-identity.** `old_CHAT_HTML == shell_with_files_inlined`. This
matters more here than for a module split, because the current literal is a non-raw `"""`
string full of `\\u2212`, `\\u23f1`, `\\u26a0` — every one becomes `\uXXXX` in a real
`.js`. Mechanical, easy to botch, and byte-identity catches it exactly.

**Also in Phase 0 — a test that makes JS validity enforceable.** All 462 tests are
`assert "..." in CHAT_HTML` substring checks, so a client syntax error ships green today.
Add a pytest that runs `node --check` on `static/app.js`, skipping if node is absent. This
is the gate that makes "everything works" mean something. It belongs here, not in Phase 3.

---

## Phase 1 — macOS design foundation

`app.css` only. **Runs last**, not first — see Sequencing.

✗ The first draft said "audit the whole stylesheet" for motion. The sheet has exactly
**five** `transition:` declarations. The work is *adding* motion, not auditing it.

### Materials
Sidebar, topbar, context menu, zoom controls, roadmap chat, command palette get
semi-transparent fills plus `backdrop-filter: saturate(180%) blur(20px)`, with an opaque
`@supports not (backdrop-filter: blur(1px))` fallback. Cards stay opaque. **Nothing inside
`#canvas` gets `backdrop-filter`** — it would wreck pan/zoom performance.

### Hairlines, radii, type
- Structural separators to `0.5px`; keep `1px` on controls.
- Nested radii must be smaller than their parent's or corners read wrong.
- `letter-spacing: -0.015em` on `--fs-2xl` and `--fs-xl`. Uppercase micro-labels keep
  positive tracking.
- Verify `--text-muted` and `--text-faint` hit WCAG AA against their real backgrounds.
  Report failures; do not silently adjust.

### Motion rules (binding)
Custom easing only — `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`,
`--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1)`. Never `ease-in`. `:active { transform:
scale(0.97) }` on every pressable control. Never enter from `scale(0)`. Popovers scale
from their trigger; modals stay centered. Only animate `transform` and `opacity`. Gate
hover behind `@media (hover: hover) and (pointer: fine)`. Everything under 300ms.

✂ **Cut: converting toasts from keyframes to transitions.** The diagnosis was wrong.
Toasts are independent flex children each with their own animation — a new sibling does
not restart an existing one, so there is nothing to fix. What actually looks bad is the
layout shift when siblings reflow, which needs FLIP, not `@starting-style`. Also
`TOAST_EXIT_MS = 160` is deliberately coupled to `toast-out 0.16s`.

Note `.toast .undo { color: #cdd8ff }` is an intentional one-off from the `731c2b0` sweep,
not an oversight. Scope the no-raw-hex check to `app.css` — `generate.py` has its own
separate untokenized `_STYLE` for the static export page and is out of scope.

---

## Phase 2 — Features

### F3 — Persist UI state  *(goes first: it touches everything)*
✗ The first draft had this running parallel to Phase 1 and F2. It cannot. It touches the
sidebar, the router, the roadmap, and the composer — do it while the surface is quiet.

Zero `localStorage` today. Persist: sidebar collapsed, expanded tree sections, last view,
per-roadmap pan/zoom, chat draft. One `prefs` helper with `get`/`set` namespaced under
`mindtrail:`, wrapped in try/catch (Safari private mode throws).

Two rules the first draft missed:
- `openRoadmapView` hard-resets `roadmapView = {zoom:1, panX:0, panY:0}` at line 1867, and
  there are five `{fitView:true}` call sites. **Restore beats fit on open; fit beats
  restore on tidy and regenerate.**
- If a persisted view points at a deleted project, fall back to Today silently.

### F1 + F4 + F5 — Canvas work  *(one agent, one file)*
✂ F5 is not a peer feature. Once F1 adds `contextmenu` handling and a `screenToCanvas`
helper it is ~15 lines. Folded in here.

**Blocker to fix first:** neither `scroll`'s pointerdown (2175) nor the node's (2370)
checks `ev.button`, so **right-click already starts a pan or a drag today**. Gate both to
`ev.button === 0` before anything else.

**Missing helper:** ✗ there is no screen↔canvas inverse transform. `applyViewport` (2095)
is forward-only. Write `screenToCanvas(clientX, clientY)` —
`(clientX - scroll.getBoundingClientRect().left - panX) / zoom`.

**F1, drag to create a dependency.** Handle on the node's right edge at
`edgeAnchor(n,'out')`'s anchor point — check it against `.node-more`, which is already
pinned bottom-right on a 220px card. Live preview line while dragging. Drop detection must
use `document.elementFromPoint(...).closest('.node')`, because the source node holds
`setPointerCapture` (2373) and targets therefore never receive `pointerover`.

✗ **The cycle guard in `_grid_positions` is not reusable.** It is cycle *tolerance* —
"don't recurse forever" — fused to column assignment. It never reports that a cycle
exists. Write a fresh reachability check.

**Validation is server-side.** `set_depends_on` is a bare `",".join(...)` with no checks,
and `handle_update_node` does not currently accept `depends_on` at all. Adding it opens an
unvalidated write boundary: reject self-links, unknown ids, cross-roadmap ids, and cycles,
in `api.py`, with tests. The client check is UX on top. Pin the wire format — accept a
list, reject a string.

**F4, multi-select.** Click selects; **Shift-click or Cmd-click extends**; **left-drag on
empty canvas marquee-selects**; **Space-held drag or middle-drag pans** (the Figma
convention — what people guess). `.panning` already exists for the cursor. The Space
tracker must ignore keystrokes in inputs and textareas.

⚠ **Riskiest step in the whole plan.** `renderRoadmap` does `view.innerHTML = ''` (2002)
and rebuilds everything, and it is called from 11 sites including every single node update
(2237, 2241, 2282, 2286). Selection state will silently vanish on any status change, so
"select six, accept all" half-works and reads as a flake. Required: keep selection in a
module-scoped `Set` outside `renderRoadmap`, reapply after each render, and add a batch
update that mutates N nodes and renders **once**.

### F6 — Link memory entries to steps
✗ Do **not** follow `due_date`'s migration path expecting a table — `ADDED_COLUMNS`
(`db.py:112-124`) adds *columns only*.

✗ And do not build `node_entries`. **There is no `entries` table** — entries live in
Chroma, so `entry_id` can never be a foreign key and every link can dangle.

**Use a `linked_entries TEXT` column**, comma-joined, exactly mirroring how `depends_on`
already works (`db.py:69`, `roadmaps.py:180`). One line in `ADDED_COLUMNS`. The read path
drops ids the store no longer has, mirroring the defensive `by_id.get(...)` at `api.py:110`.

Budget the ripple: feeding linked entries to generation changes `chat_about_roadmap`'s
signature (`roadmap_chat.py:159-166`), `_format_nodes`, and `roadmap_gen.py`, which lands
in `test_roadmap_chat.py` and `test_roadmap_gen.py`.

### F2 — Command palette (Cmd+K)  *(last: it needs backend work)*
✗ **`/api/search` cannot back this.** It is semantic vector search over `MemoryStore`
entries only (`api.py:314-345`); it decorates results with conversation and project names
but cannot *find* a project, a chat, or a node. And semantic ≠ fuzzy — typing `roadm`
matches nothing.

Build `GET /api/palette-index` returning projects, chats, and roadmap node titles for
client-side fuzzy matching, and keep `/api/search` for memory entries. This is a backend
change with tests, not "a new module."

- Cmd/Ctrl+K opens. **No animation.**
- Actions too: New chat, New note, New project, Tidy roadmap, Regenerate, Today, Profile.
- Arrows navigate, Enter runs, Escape closes.
- `?` opens a shortcuts overlay **generated from the same table** as the bindings, so it
  cannot drift. The "ignore while typing" guard lives in the table, not scattered.

**Fix the Escape pile-up first, in one place.** Three `document` keydown Escape handlers
will coexist — modal (696), sidebar search (2755, which the first draft missed), and the
palette — none stopping propagation, so one Escape closes two layers. The modal also has
no focus trap and never restores focus to its trigger. Build a topmost-layer stack.

---

## Phase 2b — Durability

The product is a memory tool that cannot back up, recover, or correct its own memory.
That is a hole in the product, not a missing nicety. These come before the polish.

### G1 — Export to markdown  *(build first)*
Nothing in the codebase exports anything; `documents.py` is the only hit for "export" and
it is an importer. Everything lives in one SQLite file plus a Chroma directory on one Mac.

`mindtrail export --out DIR [--project ID]` writing plain markdown with YAML frontmatter:
one file per conversation (turns, sources, recalled ids), one per project (instructions,
highlights, roadmap with statuses/notes/due dates/dependencies), one for the profile, and
`notes.md`. Deterministic filenames, slugified and collision-suffixed, so re-running
overwrites cleanly instead of duplicating. Add a `POST /api/export` returning the path.
This is the backup story and the portability story in one small feature.

### G2 — Persist undo
`Trash` is an in-memory `OrderedDict` behind a lock (`organize/trash.py:28-50`). Restart
the server and every recoverable delete is gone. Move it to a `deleted_conversations`
table with the payload as JSON and a `deleted_at`, keeping the same `put`/`take` API and
the same eviction bound so nothing above it changes. Purge past `MAX_HELD` on write.

### G3 — Delete and edit a single memory entry
Only `delete_conversation_entries` exists (`memory/store.py:286`) — bulk, by conversation.
One bad ingest is permanent and keeps resurfacing in recall forever.

`MemoryStore.delete_entry(entry_id)` and `update_entry(entry_id, summary=...)`, deleting
from and re-upserting into Chroma. Surface on the entry in the chat view and in search
results. Editing must re-embed, or recall silently keeps matching the old text — that is
the whole trap here.

### G4 — Undo for roadmap nodes
`handle_delete_node` hard-deletes. Reuse whatever G2 lands on; the same toast-with-undo
pattern the conversation delete already uses. Note `RoadmapNodeStore.delete` deliberately
leaves dangling `depends_on` references, so a restore must put the node back under its
original id or the edges do not come back.

### G5 — "This week" across projects
Due dates render only inside their own roadmap. Nothing answers "what is due this week",
which is the question the Today view is shaped around and cannot currently answer.
A dashboard card querying nodes across every roadmap, grouped overdue / today / this week,
each linking to its node. Sorting and the overdue colour already exist — reuse them.

### G6 — Auth
There is none, and the Dockerfile binds `0.0.0.0`. Fine on localhost, wide open the moment
it is hosted. A single shared token from `MINDTRAIL_TOKEN`, checked in one place in
`chat_server.py`, set as an httpOnly cookie after a login post. **If the variable is unset,
bind to `127.0.0.1` and skip auth** so local use stays frictionless; refuse to bind
`0.0.0.0` without a token rather than failing open. Constant-time compare.

---

## Phase 3 — Verification

Every phase must pass before it is done:

1. `pytest -q` — no regressions; new tests for new backend behavior.
2. `node --check` on `static/app.js` — now automated as a test (Phase 0).
3. Every `var(--token)` resolves; no raw hex or raw `rem` outside `:root`, **scoped to
   `app.css`**.
4. Live drive in Chrome against a scratch DB: exercise the feature, screenshot, check console.
5. `prefers-reduced-motion` honored — already covered by the existing `*` block.

**Gate 6, keyboard access — revised.** ✗ The first draft mandated a gate F1/F4/F5 cannot
pass. `.node` cards are not keyboard-reachable (`makeClickable` is only on sidebar rows and
dashboard items), and edges are bare SVG `<path>` with no tabindex and no accessible name.
Drag-to-create and marquee are pointer-only by construction.

So: direct manipulation is exempt, **but every action it provides needs a non-pointer
path** — the node overflow menu gains "Depends on…" (a node picker) and edge removal, and
"Add step here" must be reachable from a keyboard-triggered menu. Nodes get a `role` and an
accessible name.

## Sequencing

✗ The first draft's parallel diagram was falsified by its own text.

Phase 0 is done (`7412d3c`). Because the CSS and JS are now real files, backend work and
pure-client work genuinely can run in parallel — which was not true before.

```
Phase 0   static files + node --check test     DONE (7412d3c)

lane A (backend: python, api.py, chat_server.py)   lane B (client: app.js only)
  G1  export to markdown                             F3  prefs      (no backend at all)
  G2  persist undo                                   │
  G3  entry delete/edit                              F1+F4+F5  canvas
  G4  node undo                                      │
  G5  this-week card                                 │
  G6  auth                                           │
        └──────────────── join ─────────────────────┘
                  F6  memory links   (backend + canvas)
                  F2  palette        (backend + client)
                  Phase 1  design    (app.css — last, so it styles everything)
                  Phase 3  audit + visual QA
```

One writer per file at a time. Lane A owns the Python; lane B owns `app.js`. F3 is the
only client task with zero backend need, which is what makes it safe to run alongside G1.
Anything touching both lanes waits for the join.

## Risks

| Risk | Mitigation |
| --- | --- |
| Extraction changes the page | Byte-identical `CHAT_HTML` assertion |
| Stale asset caching during Phase 2 | `Cache-Control: no-store` on `/static/*` |
| **F4 selection dies on re-render** | Selection `Set` outside `renderRoadmap` + batch update |
| Unicode escapes mangled moving to `.js` | Byte-identity gate catches it |
| User draws a cycle | Fresh reachability check, server-side, with tests |
| Right-click starts a pan | `ev.button === 0` gate on both pointerdown handlers |
| Escape closes two layers | Topmost-layer stack in one place |
| Dangling entry links | Drop unknown ids on read |
| Vibrancy tanks canvas perf | No `backdrop-filter` inside `#canvas` |
| localStorage throws in private mode | try/catch every access |
