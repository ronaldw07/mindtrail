"""Turn a few typed words on a step's page into a full sub-step or daily
goal, using the step around it: "measure jump" on "Baseline jump test"
becomes a sub-step that asks for a vertical jump in inches.

Like journey_ai, every value the model sends back is checked; anything
that doesn't hold up falls back to what they typed.
"""

from __future__ import annotations

from datetime import date

from mindtrail.advice.json_reply import extract_json_object
from mindtrail.llm import LLMClient
from mindtrail.organize.habits import DAILY
from mindtrail.organize.step_tasks import MAX_DETAIL, MAX_NEEDS, MAX_TITLE, clean_due

FILL_MAX_TOKENS = 400
SCOPES = ("step", "path", "journey")

SUB_STEP_SYSTEM = (
    "Someone typed a few words to add a sub-step to one step of their plan. Turn it "
    "into a clear, checkable sub-step that fits that step. Keep their meaning; don't "
    "invent a different task.\n\n"
    "Return JSON only:\n"
    '{"title": "short, starts with a verb, under 10 words",\n'
    ' "detail": "how to do it, one or two sentences",\n'
    ' "needs": "what finishing it should produce if it is a measurement or result, '
    'e.g. Vertical jump; otherwise empty",\n'
    ' "unit": "unit for needs whenever it is a number, e.g. in, kg, min; empty only if it is not a number",\n'
    ' "due": "YYYY-MM-DD only if they named a day or deadline, else empty"}'
)

GOAL_SYSTEM = (
    "Someone typed a few words to add a daily goal (a habit they check off) to one "
    "step of their plan. Turn it into a short habit name that fits that step.\n\n"
    "Return JSON only:\n"
    '{"name": "short habit name, under 8 words, without how often",\n'
    ' "per_week": 1-7 (7 = every day; use what they said, else what suits the habit),\n'
    ' "scope": "step" if it only serves this step, "path" if it serves the whole path, '
    '"journey" if it serves the whole journey}'
)


def _clip(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _step_text(step, path_name: str, shared: bool) -> str:
    where = "every path (shared)" if shared else f'the path "{path_name}"'
    return f'STEP: "{step.title}" in {where}.\nDETAILS: {step.detail.strip() or "(none)"}'


def parse_sub_step(data: dict, typed: str, today: date) -> dict:
    due = clean_due(data.get("due"))
    needs = _clip(data.get("needs"), MAX_NEEDS)
    return {"title": _clip(data.get("title"), MAX_TITLE) or typed,
            "detail": _clip(data.get("detail"), MAX_DETAIL),
            "needs": needs,
            "unit": _clip(data.get("unit"), 20) if needs else "",
            "due": due if due >= today.isoformat() else ""}


def parse_goal(data: dict, typed: str, shared: bool) -> dict:
    try:
        per_week = min(DAILY, max(1, int(data.get("per_week"))))
    except (TypeError, ValueError):
        per_week = DAILY
    scope = data.get("scope") if data.get("scope") in SCOPES else "step"
    if shared and scope == "path":
        scope = "step"
    return {"name": _clip(data.get("name"), MAX_TITLE) or typed, "per_week": per_week, "scope": scope}


def fill_sub_step(llm: LLMClient, step, path_name: str, shared: bool, tasks: list,
                  typed: str, today: date) -> dict:
    have = "\n".join(f"  - {t.title}" for t in tasks) or "  (none yet)"
    prompt = (f"{_step_text(step, path_name, shared)}\nSUB-STEPS SO FAR:\n{have}\n"
              f"TODAY: {today.isoformat()} ({today:%A})\n\nTHEY TYPED: {typed}")
    data = extract_json_object(llm.complete(SUB_STEP_SYSTEM, prompt, max_tokens=FILL_MAX_TOKENS).text)
    return parse_sub_step(data, typed, today)


def fill_goal(llm: LLMClient, step, path_name: str, shared: bool, typed: str) -> dict:
    prompt = f"{_step_text(step, path_name, shared)}\n\nTHEY TYPED: {typed}"
    data = extract_json_object(llm.complete(GOAL_SYSTEM, prompt, max_tokens=FILL_MAX_TOKENS).text)
    return parse_goal(data, typed, shared)
