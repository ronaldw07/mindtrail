"""The weekly review: one Monday-to-Sunday week, looked back on.

Everything here is computed from stored data with no model call; the
optional prose summary (handle_week_summary) is the only one, and only
when asked.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from mindtrail.llm import LLMError
from mindtrail.organize.habits import DAILY, week_start
from mindtrail.web.life_api import focus_week
from mindtrail.web.today import local_day_start_utc

PRIORITY_COUNT = 3
PRIORITY_CHARS = 120
SUMMARY_KEY = "week_summary:"


def priorities_key(start: date) -> str:
    return f"week_priorities:{start.isoformat()}"


def _avg(values: list[int]) -> float | None:
    rated = [v for v in values if v]
    return round(sum(rated) / len(rated), 1) if rated else None


def week_review(tasks, jobs, habits, journal, focus, state, today: date, offset: int = 0) -> dict:
    start = week_start(today) + timedelta(weeks=offset)
    end = start + timedelta(days=6)
    last_day = min(end, today)  # the current week is only reviewed up to today
    days_elapsed = (last_day - start).days + 1

    done = tasks.done_since(local_day_start_utc(start))
    done = [t for t in done if t.done_at < local_day_start_utc(end + timedelta(days=1))]
    slipped = [t for t in tasks.open()
               if t.due_date and start.isoformat() <= t.due_date <= last_day.isoformat()]

    logs = habits.logs_since(start)
    habit_rows = []
    for h in habits.all():
        hits = sum(1 for d in logs.get(h.id, set()) if start <= d <= end)
        target = days_elapsed if h.target_per_week >= DAILY else h.target_per_week
        habit_rows.append({"name": h.name, "area_id": h.area_id, "done": hits, "target": target})
    hit_total = sum(min(r["done"], r["target"]) for r in habit_rows)
    target_total = sum(r["target"] for r in habit_rows)

    entries = journal.between(start.isoformat(), end.isoformat())
    prev = journal.between((start - timedelta(weeks=1)).isoformat(),
                           (start - timedelta(days=1)).isoformat())

    week_iso = (start.isoformat(), end.isoformat())
    apps = jobs.all()
    applied = [a for a in apps if a.applied_at and week_iso[0] <= a.applied_at <= week_iso[1]]
    moved = [a for a in apps if a.stage in ("oa", "interview", "offer")
             and week_iso[0] <= a.updated_at[:10] <= week_iso[1]]

    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "is_current": offset == 0,
        "done": [{"title": t.title} for t in done],
        "slipped": [{"title": t.title, "due_date": t.due_date, "task_id": t.id} for t in slipped],
        "habits": {"rows": habit_rows,
                   "rate": round(hit_total / target_total, 2) if target_total else None},
        "mood": {
            "days": [{"date": e.date, "mood": e.mood, "energy": e.energy} for e in entries],
            "avg_mood": _avg([e.mood for e in entries]),
            "avg_energy": _avg([e.energy for e in entries]),
            "prev_avg_mood": _avg([e.mood for e in prev]),
            "entries": len([e for e in entries if e.body.strip()]),
        },
        "jobs": {"applied": [a.company for a in applied],
                 "moved": [{"company": a.company, "stage": a.stage} for a in moved]},
        "focus": focus_week(focus, start),
        "priorities": state.get(priorities_key(start), []),
        "next_priorities": state.get(priorities_key(start + timedelta(weeks=1)), []),
        "summary": (state.get(SUMMARY_KEY + start.isoformat()) or {}).get("text", ""),
    }


def handle_week(deps, query: dict, today: date | None = None) -> dict:
    try:
        offset = int(query.get("offset", ["0"])[0])
    except ValueError:
        return {"error": "offset must be a whole number of weeks"}
    if offset > 0:
        return {"error": "the review only looks back"}
    return week_review(deps.tasks, deps.jobs, deps.habits, deps.journal, deps.focus, deps.state,
                       today or date.today(), offset)


def handle_save_priorities(state, body: dict) -> dict:
    try:
        start = date.fromisoformat(str(body.get("week_start", "")))
    except ValueError:
        return {"error": "week_start must be YYYY-MM-DD"}
    if start.weekday() != 0:
        return {"error": "week_start must be a Monday"}
    items = body.get("items") or []
    if not isinstance(items, list):
        return {"error": "items must be a list"}
    clean = [" ".join(str(i).split())[:PRIORITY_CHARS] for i in items]
    clean = [c for c in clean if c][:PRIORITY_COUNT]
    state.set(priorities_key(start), clean)
    return {"items": clean}


SUMMARY_PROMPT = (
    "You write a short, honest weekly review for one person from structured data "
    "about their week: to-dos finished and slipped, habit check-ins against targets, "
    "average mood and energy, job applications, focus time, and the priorities they "
    "set. Write 3-4 sentences in second person: what went well, what slipped, one "
    "pattern worth noticing, and one concrete suggestion for next week. Name specific "
    "items. Don't invent anything that isn't in the data. No headings or lists."
)


def _summary_input(review: dict) -> str:
    lines = [f"WEEK: {review['week_start']} to {review['week_end']}"]
    lines.append("FINISHED: " + ("; ".join(d["title"] for d in review["done"][:15]) or "nothing"))
    lines.append("SLIPPED: " + ("; ".join(s["title"] for s in review["slipped"][:10]) or "nothing"))
    for h in review["habits"]["rows"]:
        lines.append(f"HABIT {h['name']}: {h['done']} of {h['target']}")
    m = review["mood"]
    lines.append(f"MOOD avg {m['avg_mood']} (last week {m['prev_avg_mood']}), "
                 f"ENERGY avg {m['avg_energy']}, journal entries {m['entries']}")
    lines.append("APPLIED TO: " + (", ".join(review["jobs"]["applied"]) or "none"))
    lines.append("ADVANCED: " + (", ".join(f"{j['company']} ({j['stage']})"
                                            for j in review["jobs"]["moved"]) or "none"))
    lines.append(f"FOCUS: {review['focus']['total']} minutes")
    lines.append("PRIORITIES SET: " + ("; ".join(review["priorities"]) or "none"))
    return "\n".join(lines)


def handle_week_summary(deps, body: dict, today: date | None = None) -> dict:
    review = handle_week(deps, {"offset": [str(body.get("offset", 0))]}, today)
    if "error" in review:
        return review
    try:
        completion = deps.llm.complete(SUMMARY_PROMPT, _summary_input(review), max_tokens=300)
    except LLMError as exc:
        text = str(exc)
        return {"error": "rate limited" if "rate limited" in text else "the model was unavailable"}
    summary = completion.text.strip()
    deps.state.set(SUMMARY_KEY + review["week_start"],
                   {"text": summary, "at": datetime.now().astimezone().isoformat()})
    return {"text": summary}
