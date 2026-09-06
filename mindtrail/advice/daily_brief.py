"""On-demand prose over the Today view's deterministic daily summary.

web/api.py:handle_daily_summary assembles due dates, unblocked steps, and
recurring items with no model call, so the dashboard is free and instant
on every visit. This turns that same structured data into a short
paragraph, only when the user clicks "Brief me" - never automatically.

Follows advice/planner.py's plain-text-completion shape rather than
highlights.py's JSON shape: there is nothing here to parse back out, the
caller only ever displays the text.
"""

from __future__ import annotations

from dataclasses import dataclass

from mindtrail.llm import LLMClient

SYSTEM_PROMPT = (
    "You are a planning assistant. You are given a short structured list of "
    "someone's roadmap steps that are due today or overdue, steps that just "
    "became actionable because their dependencies are now done, recurring "
    "steps coming due within the week, and - if they've connected Google "
    "Calendar - their calendar events for today.\n\n"
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


def generate_daily_brief(llm: LLMClient, summary: dict) -> DailyBrief:
    """Raises ValueError if there is nothing worth writing a paragraph
    about - mirrors handle_daily_summary's own "empty" flag rather than
    re-deriving it."""
    if summary.get("empty"):
        raise ValueError("nothing due, overdue, or unblocked today - nothing to brief on")

    prompt = (
        _format_items("DUE TODAY OR OVERDUE", summary.get("due", []))
        + _format_items("NEWLY UNBLOCKED", summary.get("unblocked", []))
        + _format_items("RECURRING STEPS COMING DUE", summary.get("recurring", []))
        + _format_calendar(summary.get("calendar") or {})
    )
    completion = llm.complete(SYSTEM_PROMPT, prompt, max_tokens=300)
    return DailyBrief(text=completion.text, tokens=completion.tokens)
