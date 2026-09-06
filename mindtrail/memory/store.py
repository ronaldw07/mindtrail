"""Persistent, searchable store of past research.

Embeddings come from Chroma's bundled ONNX MiniLM, which runs locally and
needs no API key, so the store works offline and costs nothing.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import chromadb

from mindtrail import config
from mindtrail.organize import db


UNCATEGORIZED = "Uncategorized"
DEFAULT_KIND = "research"

# Chroma's bundled MiniLM truncates at 256 word-piece tokens - anything
# embedded past that point is silently invisible to search, no error, no
# warning. ~800 chars stays comfortably under that (roughly 4 chars per
# token for English prose), so a long entry is split into several
# vectors instead of losing everything past the first paragraph or two.
CHUNK_CHARS = 800
# How many chunk candidates to pull per requested result before
# collapsing to unique parent entries. A long entry's own chunks, and
# other entries' chunks, all compete for the same result slots, so this
# needs headroom or a real match can get crowded out before the
# collapse step runs.
CHUNK_OVERFETCH = 4

# How many candidates to pull from *each* ranked list (vector, FTS)
# before fusing - reciprocal rank fusion needs headroom too: a result
# that's #1 in one list but #15 in the other should still have a shot at
# beating a mediocre-in-both result, which it can't if either list was
# truncated to exactly `k` first.
SEARCH_OVERFETCH = 4

# Standard RRF constant (see Cormack, Clarke & Buettcher 2009). Large
# enough that a #1-vs-#2 rank difference barely moves the score, so one
# list's top pick doesn't automatically dominate the fused ranking.
RRF_K = 60


@dataclass(frozen=True)
class Entry:
    """One researched question and its synthesized answer."""

    id: str
    query: str
    summary: str
    sources: tuple[str, ...]
    created_at: str
    topic: str = ""
    key_facts: tuple[str, ...] = ()
    kind: str = DEFAULT_KIND
    """One of: research (from ask), note (manual), document (uploaded
    file), advice (generated plan)."""
    conversation_id: str = ""
    """Which conversation this belongs to. Empty for entries created
    before conversations existed, and for advice."""
    recalled_ids: tuple[str, ...] = ()
    """Ids of past entries that were recalled and folded into this
    one's research prompt - the trail a follow-up answer was built on.
    Empty for anything that isn't a research entry."""

    def with_summary(self, summary: str) -> "Entry":
        """Return a copy carrying a new summary, leaving this one untouched."""
        return replace(self, summary=summary)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """Splits long text into pieces that fit under the embedder's token
    cutoff, breaking on a sentence or paragraph boundary near the target
    length where one exists, rather than mid-word."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            if boundary > start:
                end = boundary + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end
    return chunks or [text]


def _to_entry(meta: dict, entry_id: str, doc: str = "") -> Entry:
    raw_sources = meta.get("sources", "")
    raw_facts = meta.get("key_facts", "")
    raw_recalled = meta.get("recalled_ids", "")
    # `doc` is one chunk of the embedded query+summary blob, not the
    # summary itself - it must be read back from its own metadata field.
    return Entry(
        id=entry_id,
        query=meta.get("query", ""),
        summary=meta.get("summary", doc),
        sources=tuple(s for s in raw_sources.split("\n") if s),
        created_at=meta.get("created_at", ""),
        topic=meta.get("topic", ""),
        key_facts=tuple(f for f in raw_facts.split("\n") if f),
        kind=meta.get("kind", DEFAULT_KIND),
        conversation_id=meta.get("conversation_id", ""),
        recalled_ids=tuple(r for r in raw_recalled.split("\n") if r),
    )


def _fts_match_query(text: str) -> str:
    """Build a safe FTS5 MATCH expression from free-form user text.

    Unescaped, FTS5's query syntax includes operators an ordinary search
    box shouldn't accidentally trigger: AND/OR/NOT, `-exclude`, `column:`
    filters, `*` prefix matching. A user typing any of those as plain
    words (or an unbalanced quote) would otherwise get a syntax error
    instead of a search. Each whitespace-separated token is wrapped in its
    own double-quoted phrase (embedded quotes doubled per FTS5's escaping
    rule), then joined with FTS5's default implicit AND, so the result is
    always a well-formed "every token must appear" query.
    """
    tokens = text.split()
    if not tokens:
        return '""'
    return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)


def _reciprocal_rank_fusion(ranked_lists: list[list[str]]) -> list[str]:
    """Merge ranked id lists into one ranking by reciprocal rank fusion.

    score(id) = sum(1 / (RRF_K + rank)) over every list the id appears in
    (rank counted from 1; absence from a list contributes nothing). RRF is
    used specifically because cosine similarity and BM25 live on scales
    that cannot be compared or averaged directly - RRF only looks at each
    list's *ordering*, never its raw scores, so no calibration is needed.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, entry_id in enumerate(ranked, start=1):
            scores[entry_id] = scores.get(entry_id, 0.0) + 1.0 / (RRF_K + rank)
    return [entry_id for entry_id, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]


class MemoryStore:
    """Thin wrapper over a persistent Chroma collection, plus a SQLite
    FTS5 index kept in sync alongside it for hybrid search.

    Each entry is stored as one or more chunk vectors (see _chunk_text),
    all sharing metadata and a parent_id equal to the entry's real id.
    The first chunk's Chroma row id *is* the entry id; later chunks are
    suffixed. Methods that enumerate entries (all, recent, by_conversation,
    topics, count) read only primary rows (is_chunk="0") so a long entry
    isn't counted or returned once per chunk.

    search() additionally queries a `entries_fts` SQLite table (see
    organize/db.py) indexed on the same query+summary text, and fuses the
    two ranked lists with reciprocal rank fusion - vector search alone
    misses exact strings (error codes, function names, proper nouns)
    embeddings are bad at distinguishing from their neighbors.
    """

    def __init__(
        self,
        path: str | None = None,
        collection: str | None = None,
        db_path: str | None = None,
    ):
        chroma_path = path or config.CHROMA_DIR
        self._client = chromadb.PersistentClient(path=chroma_path)
        self._collection = self._client.get_or_create_collection(
            name=collection or config.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        # Sits beside the Chroma directory by default, mirroring
        # organize/db.py's own default_db_path() convention, so a
        # MemoryStore built against a custom `path` (every test does
        # this) gets its own isolated SQLite file too, instead of
        # colliding with - or silently depending on - whatever the
        # process's real default database happens to be.
        self._db_path = db_path or str(Path(chroma_path).parent / "mindtrail.db")
        # FTS5 ships with essentially every SQLite build Python uses, but
        # is technically an optional compile-time extension. If it's
        # missing here, hybrid search quietly degrades to vector-only
        # rather than crashing every search.
        self._fts_available = db.initialize(self._db_path)

    def add(
        self,
        query: str,
        summary: str,
        sources: list[str],
        topic: str = "",
        key_facts: list[str] | None = None,
        kind: str = DEFAULT_KIND,
        conversation_id: str = "",
        recalled_ids: list[str] | None = None,
        created_at: str | None = None,
    ) -> Entry:
        """Store one researched question. Returns the created entry.

        `created_at` defaults to now; `mindtrail import` passes the
        original timestamp through explicitly so a restored entry keeps
        its place in history instead of jumping to the top of `recent`.
        """
        if not query.strip():
            raise ValueError("query must not be empty")
        if not summary.strip():
            raise ValueError("summary must not be empty")

        entry = Entry(
            id=str(uuid.uuid4()),
            query=query,
            summary=summary,
            sources=tuple(sources),
            created_at=created_at or _now_iso(),
            topic=topic,
            key_facts=tuple(key_facts or []),
            kind=kind,
            conversation_id=conversation_id,
            recalled_ids=tuple(recalled_ids or []),
        )
        self._write_chunks(entry)
        return entry

    def get(self, entry_id: str) -> Entry | None:
        """A single entry by id, for resolving a recalled_ids backlink
        into something displayable (its query text, its conversation)."""
        row = self._collection.get(ids=[entry_id])
        if not row["ids"]:
            return None
        return _to_entry(row["metadatas"][0], row["ids"][0], row["documents"][0])

    def _write_chunks(self, entry: Entry) -> None:
        # Chroma metadata values must be scalars, so list fields are
        # joined here and split back out in _to_entry. is_chunk is a
        # string, matching how every other flag field here is stored,
        # rather than relying on a particular Chroma version's bool
        # handling in `where` filters.
        base_meta = {
            "query": entry.query,
            "summary": entry.summary,
            "sources": "\n".join(entry.sources),
            "created_at": entry.created_at,
            "topic": entry.topic,
            "key_facts": "\n".join(entry.key_facts),
            "kind": entry.kind,
            "conversation_id": entry.conversation_id,
            "recalled_ids": "\n".join(entry.recalled_ids),
            "parent_id": entry.id,
        }
        chunks = _chunk_text(f"{entry.query}\n\n{entry.summary}")
        ids = [entry.id] + [f"{entry.id}::chunk{i}" for i in range(1, len(chunks))]
        self._collection.add(
            ids=ids,
            documents=chunks,
            metadatas=[
                {**base_meta, "is_chunk": "1" if i > 0 else "0"}
                for i in range(len(chunks))
            ],
        )
        self._sync_fts(entry)

    def _sync_fts(self, entry: Entry) -> None:
        """Keep the entries_fts row for this entry in step with Chroma.

        Delete-then-insert rather than an FTS5 UPDATE: `id` is an
        UNINDEXED column here, not FTS5's implicit rowid, so there's no
        single-statement upsert on it - and delete-then-insert is correct
        whether or not a row for this id already exists, which is exactly
        what every caller (add, update_entry's re-add, reindex) needs.
        """
        if not self._fts_available:
            return
        with db.connect(self._db_path) as conn:
            conn.execute("DELETE FROM entries_fts WHERE id = ?", (entry.id,))
            conn.execute(
                "INSERT INTO entries_fts (id, query, summary) VALUES (?, ?, ?)",
                (entry.id, entry.query, entry.summary),
            )

    def _delete_fts(self, entry_ids: list[str]) -> None:
        """The delete-side sibling of _sync_fts, for delete_entry and
        delete_conversation_entries - an entry removed from Chroma must
        stop surfacing in FTS results too, or a deleted entry could keep
        satisfying an old query shape forever."""
        if not self._fts_available or not entry_ids:
            return
        with db.connect(self._db_path) as conn:
            conn.executemany(
                "DELETE FROM entries_fts WHERE id = ?", [(eid,) for eid in entry_ids]
            )

    def _vector_search_ids(self, query: str, limit: int) -> list[str]:
        """Entry ids ranked by cosine similarity, nearest first, deduped
        from chunk rows down to their parent entry (see class docstring)."""
        available = self._collection.count()
        if available == 0:
            return []
        result = self._collection.query(
            query_texts=[query], n_results=min(limit * CHUNK_OVERFETCH, available)
        )
        seen: set[str] = set()
        ids = []
        for meta, doc_id in zip(result["metadatas"][0], result["ids"][0]):
            parent_id = meta.get("parent_id", doc_id)
            if parent_id in seen:
                continue
            seen.add(parent_id)
            ids.append(parent_id)
            if len(ids) >= limit:
                break
        return ids

    def _fts_search_ids(self, query: str, limit: int) -> list[str]:
        """Entry ids ranked by BM25 (FTS5's `rank`, best match first)."""
        if not self._fts_available:
            return []
        try:
            with db.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT id FROM entries_fts WHERE entries_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (_fts_match_query(query), limit),
                ).fetchall()
        except sqlite3.OperationalError:
            # Belt-and-braces: table creation already proved FTS5 works,
            # but a query-time failure should degrade to vector-only
            # rather than take the whole search down with it.
            return []
        return [row["id"] for row in rows]

    def search(self, query: str, k: int = 3) -> list[Entry]:
        """Hybrid search: SQLite FTS5 (exact terms - error codes, function
        names, proper nouns) merged with Chroma's vector search (meaning
        and paraphrase matches) via reciprocal rank fusion. Falls back to
        vector-only if this SQLite build lacks FTS5 (see __init__).
        """
        if not query.strip():
            return []

        # A non-positive n_results reaches Chroma as a malformed query, so
        # the floor is applied here rather than trusted from the caller.
        wanted = max(1, k)
        overfetch = wanted * SEARCH_OVERFETCH
        vector_ids = self._vector_search_ids(query, overfetch)
        fts_ids = self._fts_search_ids(query, overfetch)

        entries = []
        # One extra get() per candidate id, rather than reusing the
        # documents/metadata already fetched above - RRF has to reconcile
        # ids from two different sources before it knows the final order,
        # so there is no ranked, deduped (doc, meta) pair to carry through
        # until after fusion runs. Fine at this store's scale.
        for entry_id in _reciprocal_rank_fusion([vector_ids, fts_ids]):
            entry = self.get(entry_id)
            if entry is not None:
                entries.append(entry)
            if len(entries) >= wanted:
                break
        return entries

    def _primary_rows(self) -> dict:
        return self._collection.get(where={"is_chunk": "0"})

    def recent(self, n: int = 5) -> list[Entry]:
        """The n most recently added entries, newest first."""
        return self.all()[: max(1, n)]

    def all(self) -> list[Entry]:
        """Every stored entry, newest first."""
        if self._collection.count() == 0:
            return []
        data = self._primary_rows()
        entries = [
            _to_entry(meta, entry_id, doc)
            for doc, meta, entry_id in zip(
                data["documents"], data["metadatas"], data["ids"]
            )
        ]
        return sorted(entries, key=lambda e: e.created_at, reverse=True)

    def by_conversation(self, conversation_id: str) -> list[Entry]:
        """A conversation's entries, oldest first so they read as a thread."""
        if not conversation_id:
            return []
        matches = [e for e in self.all() if e.conversation_id == conversation_id]
        return sorted(matches, key=lambda e: e.created_at)

    def _all_chunk_ids(self, entry_ids: list[str]) -> list[str]:
        """Every Chroma row (primary + extra chunks) belonging to a set
        of entries. Filters client-side over an unfiltered get() rather
        than a `parent_id in [...]` where-clause, since $in support
        varies by Chroma version and this store is small enough that a
        full scan costs nothing."""
        if not entry_ids:
            return []
        wanted = set(entry_ids)
        rows = self._collection.get()
        return [
            row_id
            for row_id, meta in zip(rows["ids"], rows["metadatas"])
            if meta.get("parent_id", row_id) in wanted
        ]

    def assign_conversation(self, entry_ids: list[str], conversation_id: str) -> None:
        """Attach existing entries to a conversation.

        Chroma merges metadata on update rather than replacing it
        (verified against the installed version), so only the changed
        field is sent. Updates every chunk of each entry, not just the
        primary row, so a search hit that lands on a later chunk still
        reports the right conversation.
        """
        if not entry_ids:
            return
        ids = self._all_chunk_ids(entry_ids)
        if not ids:
            return
        self._collection.update(
            ids=ids,
            metadatas=[{"conversation_id": conversation_id} for _ in ids],
        )

    def delete_conversation_entries(self, conversation_id: str) -> int:
        """Delete every entry in a conversation. Returns how many went.

        Deleting a chat is expected to delete its content, unlike
        deleting a project, which only unfiles.
        """
        if not conversation_id:
            return 0
        doomed = [e.id for e in self.all() if e.conversation_id == conversation_id]
        if doomed:
            self._collection.delete(ids=self._all_chunk_ids(doomed))
            self._delete_fts(doomed)
        return len(doomed)

    def delete_entry(self, entry_id: str) -> bool:
        """Delete one entry (and every extra chunk it was split into).

        Returns whether an entry with that id existed. The bulk sibling
        is delete_conversation_entries; this is the single-entry path a
        bad or wrong research result needs so it stops resurfacing in
        recall forever.
        """
        ids = self._all_chunk_ids([entry_id])
        if not ids:
            return False
        self._collection.delete(ids=ids)
        self._delete_fts([entry_id])
        return True

    def update_entry(
        self,
        entry_id: str,
        summary: str | None = None,
        query: str | None = None,
    ) -> Entry | None:
        """Edit an entry's text, re-embedding it.

        Chroma embeds the document text (query+summary) once, at write
        time - it is not derived from metadata. A plain metadata update
        would leave the *old* vector in place, so recall would keep
        matching the old wording forever while the UI showed the new
        text: silent, and very hard to debug later. So this deletes the
        entry's rows and re-adds it through _write_chunks, the same path
        `add` uses, which both regenerates the embedding and re-splits
        the text if its length crossed a chunk boundary.

        Returns None if the id does not exist. Fields left as None keep
        their current value.
        """
        existing = self.get(entry_id)
        if existing is None:
            return None

        new_summary = existing.summary if summary is None else summary
        new_query = existing.query if query is None else query
        if not new_query.strip() or not new_summary.strip():
            raise ValueError("query and summary must not be empty")

        updated = replace(existing, query=new_query, summary=new_summary)
        self._collection.delete(ids=self._all_chunk_ids([entry_id]))
        self._write_chunks(updated)
        return updated

    def reindex_legacy_entries(self) -> int:
        """One-time upgrade path for entries written before chunking
        existed. They carry no is_chunk/parent_id metadata, so the
        now-filtered read methods (all, recent, by_conversation, topics,
        count) would otherwise treat them as invisible.

        Re-embeds each one through the current chunking logic, keeping
        its original id so nothing that already referenced it (a
        conversation, a delete-undo) breaks. A no-op once every entry
        has been migrated - safe to call on every startup.

        Returns how many entries were reindexed.
        """
        raw = self._collection.get()
        legacy = [
            (row_id, doc, meta)
            for row_id, doc, meta in zip(raw["ids"], raw["documents"], raw["metadatas"])
            if "is_chunk" not in meta
        ]
        for row_id, doc, meta in legacy:
            self._collection.delete(ids=[row_id])
            entry = Entry(
                id=row_id,
                query=meta.get("query", ""),
                summary=meta.get("summary", doc),
                sources=tuple(s for s in meta.get("sources", "").split("\n") if s),
                created_at=meta.get("created_at", ""),
                topic=meta.get("topic", ""),
                key_facts=tuple(
                    f for f in meta.get("key_facts", "").split("\n") if f
                ),
                kind=meta.get("kind", DEFAULT_KIND),
                conversation_id=meta.get("conversation_id", ""),
            )
            self._write_chunks(entry)
        return len(legacy)

    def topics(self) -> list[str]:
        """Distinct topic labels already in use, for reuse by new entries.

        Reusing existing labels rather than minting a fresh one each time
        is what keeps the topic list from fragmenting into near-duplicates.
        """
        return sorted({e.topic for e in self.all() if e.topic})

    def count(self) -> int:
        """How many entries are stored - not how many chunk vectors."""
        if self._collection.count() == 0:
            return 0
        return len(self._primary_rows()["ids"])
