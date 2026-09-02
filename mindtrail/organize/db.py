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
-- Columns added after the first release are applied by _add_missing_columns
-- rather than here, since CREATE TABLE IF NOT EXISTS will not alter an
-- existing table and would silently leave old databases without them.

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

-- One row, enforced by the CHECK: there is a single user here, and a
-- singleton table keeps every caller from having to pick an id.
CREATE TABLE IF NOT EXISTS profile (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    content    TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS roadmaps (
    id         TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    goal       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roadmap_nodes (
    id         TEXT PRIMARY KEY,
    roadmap_id TEXT NOT NULL REFERENCES roadmaps(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    -- proposed (agent suggestion) | accepted | rejected | done
    status     TEXT NOT NULL DEFAULT 'proposed',
    note       TEXT NOT NULL DEFAULT '',
    x          REAL NOT NULL DEFAULT 0,
    y          REAL NOT NULL DEFAULT 0,
    depends_on TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_roadmap ON roadmap_nodes(roadmap_id);
CREATE INDEX IF NOT EXISTS idx_roadmaps_project ON roadmaps(project_id);
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


# Columns introduced after the initial schema, applied to existing
# databases on startup. Kept as (table, column, definition) so adding one
# later is a single line here.
ADDED_COLUMNS = [
    ("projects", "instructions", "TEXT NOT NULL DEFAULT ''"),
    ("projects", "advice", "TEXT NOT NULL DEFAULT ''"),
    ("projects", "advice_generated_at", "TEXT NOT NULL DEFAULT ''"),
    ("projects", "advice_basis_count", "INTEGER NOT NULL DEFAULT 0"),
]


def _add_missing_columns(conn) -> None:
    for table, column, definition in ADDED_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def initialize(path: str | None = None) -> None:
    """Create tables if they do not exist, then apply later columns.

    Safe to call repeatedly; both halves are no-ops once current.
    """
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _add_missing_columns(conn)
