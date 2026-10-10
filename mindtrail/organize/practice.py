"""Coding problems you've done, and when to see them again.

A problem comes back after 1, 3, 7, then 21 days (spaced repetition,
nothing fancier). Each "reviewed" moves it to the next gap; after the last
it's done. Failing or needing help doesn't change the schedule - seeing it
again is the point.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from mindtrail.organize.db import connect, now_iso
from mindtrail.organize.jobs import clean_date

DIFFICULTIES = ("easy", "medium", "hard")
OUTCOMES = ("solo", "help", "stuck")
REVIEW_GAPS = (1, 3, 7, 21)  # days after the last time you saw it


@dataclass(frozen=True)
class Problem:
    id: str
    title: str
    url: str
    difficulty: str
    topic: str
    outcome: str
    solved_on: str
    reviews_done: int
    last_reviewed: str
    created_at: str

    def next_review(self) -> str:
        """The date it's next due, or "" when every review is done."""
        if self.reviews_done >= len(REVIEW_GAPS):
            return ""
        since = date.fromisoformat(self.last_reviewed or self.solved_on)
        return (since + timedelta(days=REVIEW_GAPS[self.reviews_done])).isoformat()


def _to_problem(row) -> Problem:
    return Problem(**{k: row[k] for k in row.keys()})


class PracticeStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def add(self, title: str, url: str = "", difficulty: str = "medium", topic: str = "",
            outcome: str = "solo", solved_on: str = "", today: date | None = None) -> Problem:
        title = title.strip()
        if not title:
            raise ValueError("a problem needs a title")
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"difficulty must be one of: {', '.join(DIFFICULTIES)}")
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of: {', '.join(OUTCOMES)}")
        url = url.strip()
        if url and not url.startswith(("http://", "https://")):
            raise ValueError("the link must start with http:// or https://")
        p = Problem(id=str(uuid.uuid4()), title=title[:160], url=url[:500], difficulty=difficulty,
                    topic=" ".join(topic.lower().split())[:40], outcome=outcome,
                    solved_on=clean_date(solved_on) or (today or date.today()).isoformat(),
                    reviews_done=0, last_reviewed="", created_at=now_iso())
        with connect(self._path) as conn:
            conn.execute("INSERT INTO practice (id, title, url, difficulty, topic, outcome, solved_on, "
                         "reviews_done, last_reviewed, created_at) VALUES (?,?,?,?,?,?,?,0,'',?)",
                         (p.id, p.title, p.url, p.difficulty, p.topic, p.outcome, p.solved_on, p.created_at))
        return p

    def get(self, problem_id: str) -> Problem | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM practice WHERE id = ?", (problem_id,)).fetchone()
        return _to_problem(row) if row else None

    def all(self) -> list[Problem]:
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM practice ORDER BY solved_on DESC, created_at DESC").fetchall()
        return [_to_problem(r) for r in rows]

    def due(self, today: date) -> list[Problem]:
        """Problems whose next review is today or earlier, longest-waiting first."""
        due = [p for p in self.all() if p.next_review() and p.next_review() <= today.isoformat()]
        return sorted(due, key=lambda p: p.next_review())

    def mark_reviewed(self, problem_id: str, today: date | None = None, outcome: str = "") -> Problem:
        p = self.get(problem_id)
        if p is None:
            raise ValueError(f"no such problem: {problem_id}")
        if outcome and outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of: {', '.join(OUTCOMES)}")
        with connect(self._path) as conn:
            conn.execute("UPDATE practice SET reviews_done = ?, last_reviewed = ?, outcome = ? WHERE id = ?",
                         (p.reviews_done + 1, (today or date.today()).isoformat(), outcome or p.outcome,
                          problem_id))
        return self.get(problem_id)

    def delete(self, problem_id: str) -> None:
        with connect(self._path) as conn:
            if conn.execute("DELETE FROM practice WHERE id = ?", (problem_id,)).rowcount == 0:
                raise ValueError(f"no such problem: {problem_id}")

    def coverage(self) -> list[dict]:
        """Per topic: how many you've done and how many you solved alone -
        where you're strong and where you needed help."""
        topics: dict[str, dict] = {}
        for p in self.all():
            t = topics.setdefault(p.topic or "other", {"topic": p.topic or "other", "total": 0, "solo": 0})
            t["total"] += 1
            t["solo"] += p.outcome == "solo"
        return sorted(topics.values(), key=lambda t: (-t["total"], t["topic"]))
