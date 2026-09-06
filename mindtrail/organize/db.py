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
-- New TABLES are safe to add anywhere in this script: CREATE TABLE IF NOT
-- EXISTS is a no-op against a database that already has one, so an old
-- database picks up new tables for free the next time initialize() runs.
-- New COLUMNS on an existing table are the opposite - IF NOT EXISTS only
-- guards table creation, not ALTER, so a column added here would silently
-- never reach a database that predates it. Those go through
-- _add_missing_columns/ADDED_COLUMNS below instead.

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

-- Held deletions, so a delete can be undone even across a restart. The
-- payload is JSON rather than typed columns - see organize/trash.py -
-- and `seq` orders puts so the oldest can be evicted past the cap
-- without relying on `deleted_at` timestamps, which can tie.
CREATE TABLE IF NOT EXISTS deleted_items (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    TEXT NOT NULL UNIQUE,
    payload    TEXT NOT NULL,
    deleted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deleted_nodes (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id    TEXT NOT NULL UNIQUE,
    payload    TEXT NOT NULL,
    deleted_at TEXT NOT NULL
);
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
    ("roadmap_nodes", "due_date", "TEXT NOT NULL DEFAULT ''"),
    ("roadmap_nodes", "linked_entries", "TEXT NOT NULL DEFAULT ''"),
    # 0 means "does not repeat". A positive value is a day interval
    # (1/7/14/30 from the UI's daily/weekly/fortnightly/monthly presets),
    # applied when the node is marked done - see RoadmapNodeStore.set_status.
    ("roadmap_nodes", "repeat_days", "INTEGER NOT NULL DEFAULT 0"),
]


def _add_missing_columns(conn) -> None:
    for table, column, definition in ADDED_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# Full-text index over memory entries (query + summary), kept in sync by
# MemoryStore on every add/update/delete - see mindtrail/memory/store.py.
# `id` is UNINDEXED: it is a lookup key back to the Chroma entry, not text
# to search over. Deliberately NOT folded into SCHEMA above and run
# through the same executescript() call: that call has no per-statement
# error isolation, so a SQLite build without the FTS5 extension compiled
# in (rare, but real - e.g. some distro-packaged Pythons) would raise
# partway through and abort every *other* table's creation along with it.
# Created and guarded separately so a missing FTS5 module degrades hybrid
# search to vector-only instead of breaking the whole database.
ENTRIES_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    id UNINDEXED, query, summary
);
"""


def _create_fts_table(conn) -> bool:
    """Returns whether the FTS5 virtual table exists (or already did)."""
    try:
        conn.executescript(ENTRIES_FTS_SCHEMA)
        return True
    except sqlite3.OperationalError:
        return False


def initialize(path: str | None = None) -> bool:
    """Create tables if they do not exist, then apply later columns.

    Safe to call repeatedly; every part is a no-op once current. Returns
    whether the FTS5 full-text table is available, so MemoryStore can
    decide once, at construction time, whether to fall back to
    vector-only search.
    """
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _add_missing_columns(conn)
        return _create_fts_table(conn)
