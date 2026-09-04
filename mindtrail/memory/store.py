"""Persistent, searchable store of past research.

Embeddings come from Chroma's bundled ONNX MiniLM, which runs locally and
needs no API key, so the store works offline and costs nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import chromadb

from mindtrail import config


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
    )


class MemoryStore:
    """Thin wrapper over a persistent Chroma collection.

    Each entry is stored as one or more chunk vectors (see _chunk_text),
    all sharing metadata and a parent_id equal to the entry's real id.
    The first chunk's Chroma row id *is* the entry id; later chunks are
    suffixed. Methods that enumerate entries (all, recent, by_conversation,
    topics, count) read only primary rows (is_chunk="0") so a long entry
    isn't counted or returned once per chunk.
    """

    def __init__(self, path: str | None = None, collection: str | None = None):
        self._client = chromadb.PersistentClient(path=path or config.CHROMA_DIR)
        self._collection = self._client.get_or_create_collection(
            name=collection or config.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def add(
        self,
        query: str,
        summary: str,
        sources: list[str],
        topic: str = "",
        key_facts: list[str] | None = None,
        kind: str = DEFAULT_KIND,
        conversation_id: str = "",
    ) -> Entry:
        """Store one researched question. Returns the created entry."""
        if not query.strip():
            raise ValueError("query must not be empty")
        if not summary.strip():
            raise ValueError("summary must not be empty")

        entry = Entry(
            id=str(uuid.uuid4()),
            query=query,
            summary=summary,
            sources=tuple(sources),
            created_at=_now_iso(),
            topic=topic,
            key_facts=tuple(key_facts or []),
            kind=kind,
            conversation_id=conversation_id,
        )
        self._write_chunks(entry)
        return entry

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

    def search(self, query: str, k: int = 3) -> list[Entry]:
        """Semantically closest past entries, nearest first."""
        if not query.strip():
            return []
        available = self._collection.count()
        if available == 0:
            return []

        # A non-positive n_results reaches Chroma as a malformed query, so
        # the floor is applied here rather than trusted from the caller.
        wanted = max(1, k)
        result = self._collection.query(
            query_texts=[query], n_results=min(wanted * CHUNK_OVERFETCH, available)
        )
        seen: set[str] = set()
        entries = []
        for doc, meta, doc_id in zip(
            result["documents"][0], result["metadatas"][0], result["ids"][0]
        ):
            parent_id = meta.get("parent_id", doc_id)
            if parent_id in seen:
                continue
            seen.add(parent_id)
            entries.append(_to_entry(meta, parent_id, doc))
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
        return len(doomed)

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
