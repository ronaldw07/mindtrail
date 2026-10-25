"""Handlers for the Measure card: did Mind Trail actually save time?

Only whole weeks that have already ended are counted. A week still in
progress has fewer minutes logged simply because it isn't over, which
would make the "after" period look better than it is.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta

from mindtrail.organize.timelog import KINDS

SPLIT_KEY = "measure_split"
RECENT = 12


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _weeks(logs, today: date, keep) -> list[date]:
    """Sorted Monday dates of finished weeks with a log whose day passes `keep`."""
    weeks = set()
    for log in logs:
        day = date.fromisoformat(log.day)
        start = week_start(day)
        if keep(day) and start + timedelta(days=7) <= today:
            weeks.add(start)
    return sorted(weeks)


def _change(before: float | None, after: float | None) -> int | None:
    """Percent drop from before to after (positive = less), or None."""
    if before is None or after is None or before <= 0:
        return None
    return round((before - after) / before * 100)


def _done_days(tasks) -> list[date]:
    days = []
    for t in tasks:
        if t.done and t.done_at:
            try:
                days.append(datetime.fromisoformat(t.done_at).astimezone().date())
            except ValueError:
                continue
    return days


def _period(logs, done_days: list[date], weeks: list[date]) -> dict:
    if not weeks:
        return {"weeks": 0, "avg": {k: None for k in KINDS}, "tasks_per_day": None}
    in_weeks = set(weeks)
    n = len(weeks)
    avg = {k: round(sum(l.minutes for l in logs if l.kind == k
                        and week_start(date.fromisoformat(l.day)) in in_weeks) / n, 1) for k in KINDS}
    done = sum(1 for d in done_days if week_start(d) in in_weeks)
    return {"weeks": n, "avg": avg, "tasks_per_day": round(done / (7 * n), 2)}


def summarize(logs, tasks, split: date | None, today: date) -> dict:
    """Weekly averages before and after `split`, and the change.

    With no split, every finished week is one period and there is nothing
    to compare yet.
    """
    done_days = _done_days(tasks)
    if split is None:
        weeks = _weeks(logs, today, lambda d: True)
        return {"split": None, "before": _period(logs, done_days, weeks),
                "after": _period(logs, done_days, []), "change": {}}
    before = _period(logs, done_days, _weeks(logs, today, lambda d: d < split))
    after = _period(logs, done_days, _weeks(logs, today, lambda d: d >= split))
    change = {k: _change(before["avg"][k], after["avg"][k]) for k in KINDS}
    b, a = before["tasks_per_day"], after["tasks_per_day"]
    change["tasks"] = None if not b else round((a - b) / b * 100) if a is not None else None
    return {"split": split.isoformat(), "before": before, "after": after, "change": change}


def handle_measure(timelog, tasks, state, today: date | None = None) -> dict:
    today = today or date.today()
    raw = state.get(SPLIT_KEY)
    try:
        split = date.fromisoformat(raw) if raw else None
    except ValueError:
        split = None
    logs = timelog.all()
    return {**summarize(logs, tasks.all(), split, today),
            "recent": [asdict(l) for l in reversed(logs)][:RECENT], "today": today.isoformat()}


def handle_log(timelog, body: dict) -> dict:
    try:
        return {"log": asdict(timelog.add(str(body.get("kind", "")), body.get("minutes"),
                                          str(body.get("day", "")), str(body.get("note", ""))))}
    except ValueError as exc:
        return {"error": str(exc)}


def handle_delete_log(timelog, log_id: str) -> dict:
    try:
        timelog.delete(log_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


def handle_set_split(state, body: dict) -> dict:
    day = str(body.get("day", "")).strip()
    if day:
        try:
            date.fromisoformat(day)
        except ValueError:
            return {"error": "day must look like 2026-10-25"}
    state.set(SPLIT_KEY, day)
    return {"ok": True, "split": day}
