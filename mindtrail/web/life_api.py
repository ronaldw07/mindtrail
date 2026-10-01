"""Request handlers for life areas, habits, and the journal.

Same contract as web/api.py and web/jobs_api.py: pure functions over the
stores, returning dicts, with bad input as {"error": ...}.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from mindtrail.organize.areas import AreaStore
from mindtrail.organize.habits import (
    DAILY,
    Habit,
    HabitStore,
    streak,
    this_week_count,
    week_start,
)
from mindtrail.organize.journal import JournalEntry, JournalStore


def handle_list_areas(areas: AreaStore) -> dict:
    return {
        "areas": [asdict(a) for a in areas.all()],
        "project_areas": areas.project_areas(),
    }


def handle_create_area(areas: AreaStore, body: dict) -> dict:
    try:
        area = areas.create(str(body.get("name", "")), str(body.get("color", "")))
    except ValueError as exc:
        return {"error": str(exc)}
    return {"area": asdict(area)}


def handle_update_area(areas: AreaStore, area_id: str, body: dict) -> dict:
    try:
        area = areas.update(area_id, str(body.get("name", "")), str(body.get("color", "")))
    except ValueError as exc:
        return {"error": str(exc)}
    return {"area": asdict(area)}


def handle_delete_area(areas: AreaStore, area_id: str) -> dict:
    try:
        areas.delete(area_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


def handle_set_project_area(areas: AreaStore, project_id: str, body: dict) -> dict:
    try:
        areas.set_project_area(project_id, str(body.get("area_id") or ""))
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


# --- habits -----------------------------------------------------------------

HEATMAP_WEEKS = 52
# Long enough that a long streak is counted in full, not cut at the heatmap.
STREAK_LOOKBACK_DAYS = 730


def habit_json(h: Habit, done: set[date], today: date) -> dict:
    heat_from = week_start(today) - timedelta(weeks=HEATMAP_WEEKS - 1)
    return {
        **asdict(h),
        "streak": streak(done, h.target_per_week, today),
        "unit": "day" if h.target_per_week >= DAILY else "week",
        "this_week": this_week_count(done, today),
        "done_today": today in done,
        "logs": sorted(d.isoformat() for d in done if d >= heat_from),
    }


def handle_list_habits(habits: HabitStore, include_archived: bool = False,
                       today: date | None = None) -> dict:
    today = today or date.today()
    logs = habits.logs_since(today - timedelta(days=STREAK_LOOKBACK_DAYS))
    return {
        "today": today.isoformat(),
        "heatmap_weeks": HEATMAP_WEEKS,
        "habits": [habit_json(h, logs.get(h.id, set()), today)
                   for h in habits.all(include_archived)],
    }


def handle_create_habit(habits: HabitStore, body: dict) -> dict:
    try:
        habit = habits.create(str(body.get("name", "")),
                              int(body.get("target_per_week", DAILY) or DAILY),
                              str(body.get("area_id", "") or ""))
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}
    return {"habit": asdict(habit)}


def handle_update_habit(habits: HabitStore, habit_id: str, body: dict) -> dict:
    try:
        habit = habits.update(habit_id, body)
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}
    return {"habit": asdict(habit)}


def handle_delete_habit(habits: HabitStore, habit_id: str) -> dict:
    try:
        habits.delete(habit_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


def handle_toggle_habit(habits: HabitStore, habit_id: str, body: dict,
                        today: date | None = None) -> dict:
    today = today or date.today()
    try:
        day = date.fromisoformat(str(body.get("date") or today.isoformat()))
        logged = habits.toggle(habit_id, day, today)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"logged": logged, "date": day.isoformat()}


# --- journal ----------------------------------------------------------------

JOURNAL_PROMPTS = (
    "What went well today?",
    "What's taking up space in your head?",
    "What would make tomorrow better?",
    "What drained you, and what gave you energy?",
    "What are you glad you did?",
    "What did you learn about yourself?",
    "Who did you enjoy time with?",
)
PROMPTS_PER_DAY = 2
JOURNAL_RECENT = 60
PREVIEW_CHARS = 120


def prompts_for(day: date) -> list[str]:
    """Two prompts, rotating daily, so the page doesn't ask the same
    thing every night."""
    start = day.toordinal() % len(JOURNAL_PROMPTS)
    return [JOURNAL_PROMPTS[(start + i) % len(JOURNAL_PROMPTS)] for i in range(PROMPTS_PER_DAY)]


def _journal_json(entry: JournalEntry | None, day: str) -> dict:
    if entry is None:
        return {"date": day, "body": "", "mood": 0, "energy": 0, "updated_at": ""}
    return {"date": entry.date, "body": entry.body, "mood": entry.mood,
            "energy": entry.energy, "updated_at": entry.updated_at}


def handle_get_journal(journal: JournalStore, day: str, today: date | None = None) -> dict:
    today = today or date.today()
    try:
        when = date.fromisoformat(day) if day else today
    except ValueError:
        return {"error": "date must be YYYY-MM-DD"}
    if when > today:
        return {"error": "can't write in the future"}
    return {
        "entry": _journal_json(journal.get(when.isoformat()), when.isoformat()),
        "today": today.isoformat(),
        "prompts": prompts_for(when),
        "recent": [
            {"date": e.date, "mood": e.mood, "energy": e.energy,
             "preview": " ".join(e.body.split())[:PREVIEW_CHARS]}
            for e in journal.recent(JOURNAL_RECENT)
        ],
    }


def handle_save_journal(journal: JournalStore, body: dict, today: date | None = None) -> dict:
    today = today or date.today()
    day = str(body.get("date") or today.isoformat())
    try:
        if date.fromisoformat(day) > today:
            return {"error": "can't write in the future"}
        entry = journal.save(day, str(body.get("body", "")),
                             body.get("mood", 0), body.get("energy", 0))
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}
    return {"entry": _journal_json(entry, day)}
