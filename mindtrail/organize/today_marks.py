"""What you've done with a to-do on Today, beyond its source's own done
flag. Checking one crosses it off but keeps it in the list for the rest
of the day; removing it (the trash can, or the next day for anything
crossed off) moves it to the archive, where it can be put back. Up to
three a day can be starred as the day's top 3."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mindtrail.organize.db import connect, now_iso

KINDS = ("task", "assignment", "step_task", "step")
ARCHIVE_LIMIT = 100
TOP_PER_DAY = 3
FIELDS = ("kind", "ref", "title", "sub", "grp", "done_on", "archived_at", "pinned_on")
SHOWN = ("kind", "ref", "title", "sub", "grp")


@dataclass(frozen=True)
class Mark:
    kind: str
    ref: str
    title: str
    sub: str
    grp: str
    done_on: str
    archived_at: str
    pinned_on: str = ""


def _item(item: dict) -> tuple[str, str, str, str, str]:
    kind, ref = str(item.get("kind", "")), str(item.get("ref", "")).strip()
    if kind not in KINDS or not ref:
        raise ValueError("unknown to-do")
    title = " ".join(str(item.get("title", "")).split())[:200]
    if not title:
        raise ValueError("a to-do needs a title")
    return kind, ref, title, str(item.get("sub", ""))[:200], str(item.get("group", ""))[:20]


class TodayMarks:
    def __init__(self, path: str | None = None):
        self._path = path

    def _get(self, conn, kind: str, ref: str) -> Mark | None:
        row = conn.execute("SELECT * FROM today_marks WHERE kind = ? AND ref = ?", (kind, ref)).fetchone()
        return Mark(*[row[k] for k in FIELDS]) if row else None

    def _save(self, item: dict, **fields) -> Mark:
        kind, ref, title, sub, grp = _item(item)
        with connect(self._path) as conn:
            old = self._get(conn, kind, ref)
            row = {**(asdict(old) if old else {"done_on": "", "archived_at": "", "pinned_on": ""}),
                   "kind": kind, "ref": ref, "title": title, "sub": sub, "grp": grp, **fields}
            if fields.get("pinned_on") and not (old and old.pinned_on == fields["pinned_on"]):
                taken = conn.execute("SELECT COUNT(*) FROM today_marks WHERE pinned_on = ? AND archived_at = ''",
                                     (fields["pinned_on"],)).fetchone()[0]
                if taken >= TOP_PER_DAY:
                    raise ValueError(f"You've picked {TOP_PER_DAY} for today. Unstar one first.")
            conn.execute(
                "INSERT OR REPLACE INTO today_marks (kind, ref, title, sub, grp, done_on, archived_at, pinned_on) "
                "VALUES (:kind, :ref, :title, :sub, :grp, :done_on, :archived_at, :pinned_on)", row)
            return self._get(conn, kind, ref)

    def _clear(self, kind: str, ref: str, field_name: str) -> None:
        """Unset one mark; a row left with none is dropped."""
        with connect(self._path) as conn:
            conn.execute(f"UPDATE today_marks SET {field_name} = '' WHERE kind = ? AND ref = ?", (kind, ref))
            conn.execute("DELETE FROM today_marks WHERE kind = ? AND ref = ? AND done_on = '' "
                         "AND archived_at = '' AND pinned_on = ''", (kind, ref))

    def cross(self, item: dict, day: str) -> Mark:
        return self._save(item, done_on=day)

    def archive(self, item: dict, day: str, done: bool = False) -> Mark:
        return self._save(item, archived_at=now_iso(), **({"done_on": day} if done else {}))

    def pin(self, item: dict, day: str) -> Mark:
        return self._save(item, pinned_on=day)

    def unpin(self, kind: str, ref: str) -> None:
        self._clear(kind, ref, "pinned_on")

    def uncross(self, kind: str, ref: str) -> None:
        self._clear(kind, ref, "done_on")

    def forget(self, kind: str, ref: str) -> None:
        """Put back from the archive: Today shows it as its source does."""
        with connect(self._path) as conn:
            conn.execute("DELETE FROM today_marks WHERE kind = ? AND ref = ?", (kind, ref))

    def for_today(self, day: str) -> dict:
        """crossed: still shown, struck through. pinned: today's top 3.
        hidden: 'kind:ref' keys Today leaves out. Anything crossed off on
        an earlier day is archived first."""
        with connect(self._path) as conn:
            conn.execute("UPDATE today_marks SET archived_at = ? "
                         "WHERE archived_at = '' AND done_on != '' AND done_on < ?", (now_iso(), day))
            rows = conn.execute("SELECT * FROM today_marks").fetchall()
        live = [r for r in rows if not r["archived_at"]]
        return {"crossed": [{k: r[k] for k in SHOWN} for r in live if r["done_on"]],
                "pinned": [{k: r[k] for k in SHOWN} for r in live if r["pinned_on"] == day],
                "hidden": [f"{r['kind']}:{r['ref']}" for r in rows if r["archived_at"]]}

    def archived(self) -> list[dict]:
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM today_marks WHERE archived_at != '' "
                                "ORDER BY archived_at DESC LIMIT ?", (ARCHIVE_LIMIT,)).fetchall()
        return [{k: r[k] for k in FIELDS} for r in rows]
