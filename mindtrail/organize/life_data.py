"""Export/import for the structured life-dashboard tables.

Projects, chats, and roadmaps export as readable markdown (organize/
export.py). Jobs, tasks, habits, and the rest are rows, not documents,
so they go into one `life.json` as {table: [row, ...]} - lossless, and
adding a table to the backup is one line in LIFE_TABLES rather than a new
writer and parser pair.

Order matters: a table must come after any table it references.
"""

from __future__ import annotations

import sqlite3

from mindtrail.organize.db import connect

LIFE_FILE = "life.json"

LIFE_TABLES = (
    "areas",
    "applications",
    "tasks",
    "gmail_seen",
    "app_state",
)


def dump_tables(db_path: str | None) -> dict[str, list[dict]]:
    with connect(db_path) as conn:
        return {
            table: [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
            for table in LIFE_TABLES
        }


def _columns(conn, table: str) -> tuple[list[str], list[str]]:
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    names = [c["name"] for c in info]
    pk = [c["name"] for c in sorted(info, key=lambda c: c["pk"]) if c["pk"]]
    return names, pk


def load_tables(
    db_path: str | None, data: dict, overwrite: bool
) -> tuple[int, int, int, list[str]]:
    """Insert rows by primary key. An existing row is skipped, or updated
    in place with `overwrite`. Returns (created, skipped, failed, warnings).

    Columns the current schema doesn't have are dropped, so an export
    from a newer version still imports what this version understands.
    """
    created = skipped = failed = 0
    warnings: list[str] = []
    with connect(db_path) as conn:
        for table in LIFE_TABLES:
            rows = data.get(table) or []
            if not isinstance(rows, list):
                failed += 1
                warnings.append(f"{table}: expected a list of rows")
                continue
            names, pk = _columns(conn, table)
            for row in rows:
                if not isinstance(row, dict) or any(k not in row for k in pk):
                    failed += 1
                    warnings.append(f"{table}: row without a primary key, skipped")
                    continue
                values = {k: row[k] for k in names if k in row}
                where = " AND ".join(f"{k} = ?" for k in pk)
                key = tuple(values[k] for k in pk)
                try:
                    exists = conn.execute(
                        f"SELECT 1 FROM {table} WHERE {where}", key
                    ).fetchone()
                    if exists and not overwrite:
                        skipped += 1
                        continue
                    if exists:
                        rest = [k for k in values if k not in pk]
                        if rest:
                            conn.execute(
                                f"UPDATE {table} SET "
                                + ", ".join(f"{k} = ?" for k in rest)
                                + f" WHERE {where}",
                                (*(values[k] for k in rest), *key),
                            )
                    else:
                        cols = list(values)
                        conn.execute(
                            f"INSERT INTO {table} ({', '.join(cols)}) "
                            f"VALUES ({', '.join('?' for _ in cols)})",
                            tuple(values.values()),
                        )
                    created += 1
                except sqlite3.Error as exc:
                    failed += 1
                    warnings.append(f"{table} {key}: {exc}")
    return created, skipped, failed, warnings
