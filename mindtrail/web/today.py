"""Life-dashboard additions to the Today summary: open tasks, application
deadlines, and the choice of the one "push your work forward" item.

Kept out of web/api.py (already long) and called from
handle_daily_summary, which owns the roadmap half of the same summary.
"""

from __future__ import annotations

from datetime import date, timedelta

from mindtrail.organize.habits import DAILY, HabitStore, streak, this_week_count
from mindtrail.organize.jobs import JobStore
from mindtrail.organize.tasks import TaskStore

WEEK_DAYS = 7
DEADLINE_DAYS = 7
URGENT_DEADLINE_DAYS = 3


def _bucket(due: date, today: date) -> str:
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    if due <= today + timedelta(days=WEEK_DAYS):
        return "this_week"
    return "later"


def _date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def open_tasks(tasks: TaskStore, jobs: JobStore, today: date) -> list[dict]:
    """Open tasks due within the week (or overdue), soonest first, each
    labeled with its application's company if it has one."""
    companies = {a.id: a.company for a in jobs.all()}
    items = []
    for t in tasks.open():
        due = _date(t.due_date) if t.due_date else None
        if due is None:
            continue
        bucket = _bucket(due, today)
        if bucket == "later":
            continue
        items.append({
            "kind": "task", "task_id": t.id, "title": t.title, "due_date": t.due_date,
            "bucket": bucket, "application_id": t.application_id,
            "company": companies.get(t.application_id, ""),
        })
    items.sort(key=lambda i: i["due_date"])
    return items


def upcoming_deadlines(jobs: JobStore, today: date) -> list[dict]:
    """Saved-but-not-applied applications whose deadline is within the
    week. Past deadlines are left out - there's nothing left to do."""
    items = []
    for a in jobs.all():
        due = _date(a.deadline) if a.deadline else None
        if a.stage != "saved" or due is None:
            continue
        if not today <= due <= today + timedelta(days=DEADLINE_DAYS):
            continue
        role = f" ({a.role})" if a.role else ""
        items.append({
            "kind": "deadline", "application_id": a.id, "company": a.company,
            "title": f"Apply to {a.company}{role}", "due_date": a.deadline,
            "bucket": _bucket(due, today),
        })
    items.sort(key=lambda i: i["due_date"])
    return items


def habits_today(habits: HabitStore, today: date) -> list[dict]:
    """Each active habit with whether it's done today and its streak."""
    logs = habits.logs_since(today - timedelta(days=730))
    items = []
    for h in habits.all():
        done = logs.get(h.id, set())
        items.append({
            "id": h.id, "name": h.name, "area_id": h.area_id,
            "target_per_week": h.target_per_week, "done_today": today in done,
            "streak": streak(done, h.target_per_week, today),
            "unit": "day" if h.target_per_week >= DAILY else "week",
            "this_week": this_week_count(done, today),
        })
    return items


def pick_top_priority(summary: dict, today: date) -> dict | None:
    """Overdue first, then due today, then a deadline within three days,
    then the next unblocked roadmap step, then anything else this week.
    Each candidate keeps its own fields plus a `kind` the client uses to
    decide where "Let's do it" goes."""
    urgent_by = (today + timedelta(days=URGENT_DEADLINE_DAYS)).isoformat()
    candidates = []
    for item in summary.get("due", []):
        candidates.append((0 if item["bucket"] == "overdue" else 1, item, "step"))
    for item in summary.get("tasks", []):
        rank = {"overdue": 0, "today": 1}.get(item["bucket"], 4)
        candidates.append((rank, item, "task"))
    for item in summary.get("deadlines", []):
        candidates.append((2 if item["due_date"] <= urgent_by else 4, item, "deadline"))
    for item in summary.get("unblocked", []):
        candidates.append((3, item, "step"))
    if not candidates:
        return None
    rank, item, kind = min(candidates, key=lambda c: (c[0], c[1].get("due_date") or "9999"))
    return {**item, "kind": kind}
