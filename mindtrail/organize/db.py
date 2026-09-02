"""SQLite storage for projects and conversations.

Chroma holds entries and their embeddings; this holds the mutable
organizational state around them. Renaming a project or pinning a chat
should not touch a vector index, and an empty project has nowhere to live
in Chroma at all.

A connection is opened per operation rather than shared. The chat server
is threaded, sqlite3 connections are not thread-safe by default, and
per-operation connections avoid needing a lock around every read.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from mindtrail import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    pinned     INTEGER NOT NULL DEFAULT 0,
    unread     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_project
    ON conversations(project_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> str:
    """Sits beside the Chroma directory so both move together."""
    return str(Path(config.CHROMA_DIR).parent / "mindtrail.db")


@contextmanager
def connect(path: str | None = None):
    """Yield a connection with foreign keys enforced and rows as mappings.

    Foreign keys are off by default in SQLite and must be enabled per
    connection. Without it, ON DELETE SET NULL silently does nothing and
    deleting a project would orphan its conversations instead of
    unfiling them.
    """
    target = path or default_db_path()
    Path(target).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize(path: str | None = None) -> None:
    """Create tables if they do not exist. Safe to call repeatedly."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)
