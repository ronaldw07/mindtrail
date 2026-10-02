"""Prose over the Today view's deterministic daily summary.

web/api.py:handle_daily_summary assembles due dates, unblocked steps,
to-dos, and deadlines with no model call, so the dashboard is free and
instant on every visit. This turns that same data into a short paragraph.
cached_brief makes it automatic without being a model call per visit: it
regenerates only when the day's data actually changed.

Follows advice/planner.py's plain-text-completion shape rather than
highlights.py's JSON shape: there is nothing here to parse back out, the
caller only ever displays the text.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime

from mindtrail.llm import LLMClient, LLMError

SYSTEM_PROMPT = (
    "You are a planning assistant. You are given a short structured list of "
    "someone's roadmap steps that are due today or overdue, to-dos due this "
    "week (some tied to job applications), job application deadlines they "
    "haven't applied for yet, steps that just became actionable because "
    "their dependencies are now done, recurring steps coming due within the "
    "week, and - if they've connected Google Calendar - their calendar "
    "events for today.\n\n"
    "Write one short paragraph (2-4 sentences) telling them what to focus "
    "on today, in plain conversational language. Name specific step titles "
    "and event names rather than vague categories. If anything is overdue, "
    "say so plainly rather than burying it in the middle. Do not invent "
    "anything that isn't in the list, and do not pad with generic advice."
)

# Enough items to cover a busy day without the prompt ballooning - a
# person with 20 overdue steps needs "you have 20 overdue steps", not a
# paragraph trying to name all 20.
MAX_ITEMS_PER_SECTION = 8


@dataclass(frozen=True)
class DailyBrief:
    text: str
    tokens: int


def _format_items(label: str, items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        f"- {item['title']} ({item['project_name']})"
        + (f", due {item['due_date']}" if item.get("due_date") else "")
        for item in items[:MAX_ITEMS_PER_SECTION]
    ]
    return f"{label}:\n" + "\n".join(lines) + "\n\n"


def _format_calendar(calendar: dict) -> str:
    """Only included when a connection actually produced events - a
    disconnected or errored calendar contributes nothing here rather than
    telling the model about its own plumbing."""
    if not calendar.get("connected") or not calendar.get("events"):
        return ""
    lines = [
        f"- {e['title']}" + ("" if e["all_day"] else f" at {e['start']}")
        for e in calendar["events"][:MAX_ITEMS_PER_SECTION]
    ]
    return "CALENDAR EVENTS TODAY:\n" + "\n".join(lines) + "\n\n"


def _format_tasks(label: str, items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        f"- {item['title']}" + (f" ({item['company']})" if item.get("company") else "")
        + (f", due {item['due_date']}" if item.get("due_date") else "")
        for item in items[:MAX_ITEMS_PER_SECTION]
    ]
    return f"{label}:\n" + "\n".join(lines) + "\n\n"


def generate_daily_brief(llm: LLMClient, summary: dict) -> DailyBrief:
    """Raises ValueError if there is nothing worth writing a paragraph
    about - mirrors handle_daily_summary's own "empty" flag rather than
    re-deriving it."""
    if summary.get("empty"):
        raise ValueError("nothing due, overdue, or unblocked today - nothing to brief on")

    prompt = (
        _format_items("DUE TODAY OR OVERDUE", summary.get("due", []))
        + _format_tasks("TO-DOS DUE THIS WEEK", summary.get("tasks", []))
        + _format_tasks("APPLICATION DEADLINES (NOT APPLIED YET)", summary.get("deadlines", []))
        + _format_tasks("SCHOOL ASSIGNMENTS DUE", [
            {"title": a["title"], "due_date": a["due"]} for a in summary.get("assignments", [])])
        + _format_items("NEWLY UNBLOCKED", summary.get("unblocked", []))
        + _format_items("RECURRING STEPS COMING DUE", summary.get("recurring", []))
        + _format_calendar(summary.get("calendar") or {})
    )
    completion = llm.complete(SYSTEM_PROMPT, prompt, max_tokens=300)
    return DailyBrief(text=completion.text, tokens=completion.tokens)


# --- cached, automatic brief ---------------------------------------------

CACHE_KEY = "daily_brief"
# Checking off three to-dos in a row shouldn't cost three model calls -
# within this window a changed day keeps showing the last brief.
REFRESH_MIN_SECONDS = 15 * 60


def brief_input_hash(summary: dict, today: date) -> str:
    """What the brief is about, minus anything that changes without the
    day changing (calendar fetch time, counters)."""
    def titles(key: str) -> list:
        return [(i.get("title"), i.get("due_date")) for i in summary.get(key, [])]

    events = [(e.get("title"), e.get("start"))
              for e in (summary.get("calendar") or {}).get("events", []) or []]
    basis = {"date": today.isoformat(), "events": events,
             **{k: titles(k) for k in ("due", "tasks", "deadlines", "unblocked", "recurring")},
             "assignments": [(a.get("title"), a.get("due")) for a in summary.get("assignments", [])]}
    return hashlib.sha1(json.dumps(basis, sort_keys=True).encode()).hexdigest()


def cached_brief(llm, summary: dict, state, now: datetime, force: bool = False) -> dict:
    """{"text", "generated_at", "stale"} - from the cache when the day's
    data hasn't changed (no model call), regenerated when it has. On a
    model failure the last brief is returned with an "error" alongside."""
    today = now.date()
    if summary.get("empty"):
        return {"text": "", "empty": True}
    digest = brief_input_hash(summary, today)
    cache = state.get(CACHE_KEY) or {}
    if cache.get("hash") == digest:
        return {"text": cache["text"], "generated_at": cache["generated_at"], "stale": False}

    recent = False
    if cache.get("date") == today.isoformat():
        try:
            age = (now - datetime.fromisoformat(cache["generated_at"])).total_seconds()
            recent = age < REFRESH_MIN_SECONDS
        except (KeyError, ValueError, TypeError):
            recent = False
    if recent and not force:
        return {"text": cache["text"], "generated_at": cache["generated_at"], "stale": True}

    try:
        brief = generate_daily_brief(llm, summary)
    except (LLMError, ValueError) as exc:
        if cache.get("text"):
            return {"text": cache["text"], "generated_at": cache.get("generated_at", ""),
                    "stale": True, "error": str(exc)}
        raise
    entry = {"hash": digest, "text": brief.text.strip(), "date": today.isoformat(),
             "generated_at": now.isoformat(timespec="seconds")}
    state.set(CACHE_KEY, entry)
    return {"text": entry["text"], "generated_at": entry["generated_at"], "stale": False}
