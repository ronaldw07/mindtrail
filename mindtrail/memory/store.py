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


@dataclass(frozen=True)
class Entry:
    """One researched question and its synthesized answer."""

    id: str
    query: str
    summary: str
    sources: tuple[str, ...]
    created_at: str

    def with_summary(self, summary: str) -> "Entry":
        """Return a copy carrying a new summary, leaving this one untouched."""
        return replace(self, summary=summary)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_entry(doc: str, meta: dict, entry_id: str) -> Entry:
    raw_sources = meta.get("sources", "")
    return Entry(
        id=entry_id,
        query=meta.get("query", ""),
        summary=doc,
        sources=tuple(s for s in raw_sources.split("\n") if s),
        created_at=meta.get("created_at", ""),
    )


class MemoryStore:
    """Thin wrapper over a persistent Chroma collection."""

    def __init__(self, path: str | None = None, collection: str | None = None):
        self._client = chromadb.PersistentClient(path=path or config.CHROMA_DIR)
        self._collection = self._client.get_or_create_collection(
            name=collection or config.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, query: str, summary: str, sources: list[str]) -> Entry:
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
        )
        # Chroma metadata values must be scalars, so sources are joined here
        # and split back out in _to_entry.
        self._collection.add(
            ids=[entry.id],
            documents=[f"{entry.query}\n\n{entry.summary}"],
            metadatas=[
                {
                    "query": entry.query,
                    "sources": "\n".join(entry.sources),
                    "created_at": entry.created_at,
                }
            ],
        )
        return entry

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
            query_texts=[query], n_results=min(wanted, available)
        )
        return [
            _to_entry(doc, meta, entry_id)
            for doc, meta, entry_id in zip(
                result["documents"][0], result["metadatas"][0], result["ids"][0]
            )
        ]

    def recent(self, n: int = 5) -> list[Entry]:
        """The n most recently added entries, newest first."""
        if self._collection.count() == 0:
            return []
        data = self._collection.get()
        entries = [
            _to_entry(doc, meta, entry_id)
            for doc, meta, entry_id in zip(
                data["documents"], data["metadatas"], data["ids"]
            )
        ]
        return sorted(entries, key=lambda e: e.created_at, reverse=True)[: max(1, n)]

    def count(self) -> int:
        return self._collection.count()
