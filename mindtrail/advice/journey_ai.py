"""The model's three jobs on the journey: chat that proposes changes,
a review of a past year, and matching outside evidence to steps.

Like advice/roadmap_chat.py, none of this writes anything. Each function
returns proposals; the caller shows them and applies only what you
accept. Every id and term the model sends back is checked against the
real journey, and anything that doesn't check out is dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mindtrail.advice.json_reply import extract_json_object
from mindtrail.llm import LLMClient
from mindtrail.organize.roadmaps import STATUSES
from mindtrail.organize.step_tasks import clean_due
from mindtrail.organize.terms import is_term, term_label, term_rank

CHAT_MAX_TOKENS = 2500
REVIEW_MAX_TOKENS = 4000
EVIDENCE_MAX_TOKENS = 3000
MAX_ACTIONS = 8
MAX_SUGGESTIONS = 12

# What the model sees for each status, so "accepted" can't be read as "finished".
STATUS_WORDS = {"accepted": "planned", "proposed": "suggested", "done": "done", "rejected": "skipped"}

ACTION_TYPES = ("add_step", "set_status", "move_term", "set_note", "delete_step",
                "create_track", "duplicate_track", "rename_track", "create_journey", "set_folder",
                "plan_step", "add_daily_goal", "edit_step", "edit_track", "delete_track",
                "edit_journey", "delete_journey", "edit_sub_step", "delete_sub_step",
                "edit_daily_goal", "delete_daily_goal", "remember", "edit_fact", "forget",
                "set_term_note", "log_daily_goal", "set_layout")
# Actions about a whole journey: on the Journeys page they must name which.
JOURNEY_LEVEL = ("create_track", "set_folder", "edit_journey", "delete_journey", "set_term_note",
                 "set_layout")
LAYOUT_WORDS = {"terms": "school terms", "map": "a path map"}
MAX_FACTS_CHARS = 3000   # how much of what they've told it the assistant reads
MAX_SUB_STEPS = 10

TERM_RULES = (
    "Terms are written like 2026-fall, 2027-winter, 2027-spring, 2027-summer: the "
    "calendar year the term happens in, then fall, winter, spring or summer. An "
    "academic year runs fall, winter, spring, summer, so Year 1 starting 2025 is "
    "2025-fall, 2026-winter, 2026-spring, 2026-summer."
)


@dataclass(frozen=True)
class JourneyContext:
    """Everything the model is shown, plus what its answer is checked against."""
    text: str
    track_ids: dict[str, str] = field(default_factory=dict)   # id -> name
    node_titles: dict[str, str] = field(default_factory=dict)  # id -> title
    unfinished: dict[str, int] = field(default_factory=dict)  # id -> sub-steps not done yet
    task_titles: dict[str, str] = field(default_factory=dict)  # sub-step id -> title
    goal_names: dict[str, str] = field(default_factory=dict)  # daily goal id -> name
    journey_ids: dict[str, str] = field(default_factory=dict)  # journey id -> name
    home: bool = False   # on the Journeys page, looking at every journey at once
    facts: tuple = ()    # what they've told the app about themselves, one per line
    owner: dict[str, str] = field(default_factory=dict)  # any id -> the journey it's in, by name


def profile_facts(profile: str) -> tuple:
    """The profile as a list of facts: one per non-blank line."""
    return tuple(" ".join(line.split()) for line in profile.splitlines() if line.strip())


def _facts_text(facts: tuple) -> str:
    if not facts:
        return "WHAT YOU KNOW ABOUT THEM: nothing yet."
    lines, used = [], 0
    for n, f in enumerate(facts, 1):
        used += len(f)
        if used > MAX_FACTS_CHARS:
            lines.append(f"  ({len(facts) - n + 1} more not shown)")
            break
        lines.append(f"  {n}. {f}")
    return "WHAT YOU KNOW ABOUT THEM (their own facts, numbered):\n" + "\n".join(lines)


def build_context(start_year: int, current_term: str, shared, tracks: list,
                  steps_by_track: dict[str, list], profile: str = "",
                  purpose: str = "", kind: str = "career", folder: str = "",
                  others: list[dict] = (), today: str = "", focus=None,
                  progress: dict | None = None, tasks_by_node: dict | None = None,
                  goals_by_node: dict | None = None, journey_id: str = "",
                  name: str = "", reflections: dict | None = None,
                  layout: str = "terms", goals_by_track: dict | None = None,
                  journey_goals: list = ()) -> JourneyContext:
    """focus is (step, its sub-steps, its daily goals) for the step the user
    has open; progress maps step id -> (sub-steps done, total);
    tasks_by_node and goals_by_node list each step's sub-steps and daily
    goals (Habit rows) with their ids, so they can be edited by asking."""
    progress, tasks_by_node, goals_by_node = progress or {}, tasks_by_node or {}, goals_by_node or {}
    goals_by_track = goals_by_track or {}
    what = "a 4-year CS degree and the career it leads to" if kind == "career" else "a personal journey"
    named = (f' id={journey_id}' if journey_id else "") + (f' "{name}"' if name else "")
    is_map = layout == "map"
    lines = [f"JOURNEY{named}: {what}, laid out as a PATH MAP: each track is an ordered line of steps, "
             "first to last, with no terms; a step may have a date." if is_map else
             f"JOURNEY{named}: {what}, laid out in terms from fall {start_year} for 4 years."]
    if purpose.strip():
        lines.append(f"WHAT IT'S FOR: {purpose.strip()[:500]}")
    lines.append(f"FOLDER: {folder}" if folder else "FOLDER: none")
    if others:
        lines.append("OTHER JOURNEYS: " + "; ".join(
            o["name"] + (f" (folder {o['folder']})" if o.get("folder") else "") for o in others))
    lines.append((f"TODAY: {today}." if today else "") if is_map else
                 f"CURRENT TERM: {current_term} ({term_label(current_term)})."
                 + (f" TODAY: {today}." if today else ""))
    notes = {t: x for t, x in (reflections or {}).items() if x.strip()}
    if notes:
        lines.append("TERM NOTES (what they wrote happened each term): " + "; ".join(
            f"{t}: {' '.join(x.split())[:300]}" for t, x in sorted(notes.items())))
    facts = profile_facts(profile)
    if facts:
        lines.append(_facts_text(facts))
    track_ids, node_titles, task_titles, goal_names = {}, {}, {}, {}
    if journey_goals:
        lines.append("DAILY GOALS FOR THE WHOLE JOURNEY:")
        for g in journey_goals:
            goal_names[g.id] = g.name
            lines.append(f"  daily goal id={g.id}: {g.name} ({_how_often(g.target_per_week)})")
    for track in ([shared] if shared else []) + list(tracks):
        is_shared = shared is not None and track.id == shared.id
        label = "SHARED (shown on every track)" if is_shared else f"TRACK {track.name or track.goal}"
        lines.append(f"\n{label} id={track.id} goal: {track.goal}")
        track_ids[track.id] = track.name or track.goal
        for g in goals_by_track.get(track.id, []):
            goal_names[g.id] = g.name
            lines.append(f"  daily goal for this whole track id={g.id}: {g.name} ({_how_often(g.target_per_week)})")
        steps = steps_by_track.get(track.id, [])
        if is_map:
            steps = sorted(steps, key=lambda n: (n.position, n.created_at))
        if not steps:
            lines.append("  (no steps yet)")
        for n in steps:
            node_titles[n.id] = n.title
            where = (f"by {n.due_date}" if n.due_date else "no date") if is_map else (n.term or "no term")
            line = f"  - id={n.id} [{STATUS_WORDS.get(n.status, n.status)}] {where}: {n.title}"
            if n.detail:
                line += f" - {n.detail[:160]}"
            if n.note:
                line += f" (note: {n.note[:160]})"
            if n.id in progress:
                line += f" [sub-steps {progress[n.id][0]}/{progress[n.id][1]} done]"
            lines.append(line)
            for t in tasks_by_node.get(n.id, []):
                task_titles[t.id] = t.title
                lines.append(f"      sub-step id={t.id} [{'done' if t.done else 'to do'}] {t.title}"
                             + (f" (due {t.due})" if t.due else "") + _result_text(t))
            for g in goals_by_node.get(n.id, []):
                goal_names[g.id] = g.name
                lines.append(f"      daily goal id={g.id}: {g.name} ({_how_often(g.target_per_week)})")
    if focus is not None:
        lines.append(_focus_text(*focus))
    unfinished = {k: total - done for k, (done, total) in progress.items()}
    owner = dict.fromkeys([*track_ids, *node_titles, *task_titles, *goal_names], name or "this journey")
    return JourneyContext("\n".join(lines), track_ids, node_titles, unfinished, task_titles, goal_names,
                          {journey_id: name or "this journey"} if journey_id else {}, facts=facts,
                          owner=owner)


def build_home_context(sections: list[JourneyContext], profile: str = "",
                       today: str = "") -> JourneyContext:
    """Every journey at once, for the assistant on the Journeys page. Each
    section is one journey's own context, built with its id and name."""
    head = ["THEY ARE ON THE JOURNEYS PAGE, looking at all of their journeys at once."
            + (f" TODAY: {today}." if today else "")]
    facts = profile_facts(profile)
    head.append(_facts_text(facts))
    if not sections:
        head.append("They have no journeys yet.")
    merged: dict[str, dict] = {k: {} for k in ("track_ids", "node_titles", "unfinished", "task_titles",
                                               "goal_names", "journey_ids", "owner")}
    for sec in sections:
        for key, values in merged.items():
            values.update(getattr(sec, key))
    text = "\n\n".join(["\n".join(head)] + ["=" * 8 + "\n" + sec.text for sec in sections])
    return JourneyContext(text, home=True, facts=facts, **merged)


def _focus_text(step, tasks: list, goals: list = ()) -> str:
    lines = [f'\nTHEY HAVE THIS STEP OPEN: id={step.id} "{step.title}" '
             f"({term_label(step.term) if step.term else 'no term'}). Its sub-steps, in order:"]
    lines += [f"  {n}. [{'done' if t.done else 'to do'}] {t.title}" + (f" (due {t.due})" if t.due else "")
              for n, t in enumerate(tasks, 1)] or ["  (none yet)"]
    lines.append("Its daily goals:")
    lines += [f"  - {g['name']} ({_how_often(g['target_per_week'])}, {g['streak']}-{g['unit']} streak, "
              f"{g['this_week']} this week)" for g in goals] or ["  (none yet)"]
    return "\n".join(lines)


def _result_text(t) -> str:
    """What a sub-step asks them to record, and what they recorded."""
    if not getattr(t, "needs", ""):
        return ""
    what = t.needs + (f" ({t.unit})" if t.unit else "")
    return f" [records {what}: {t.result}]" if t.result else f" [asks for {what}, not entered yet]"


def _how_often(per_week: int) -> str:
    return "every day" if per_week >= 7 else f"{per_week}x a week"


def _term(value) -> str:
    value = str(value or "").strip().lower()
    return value if is_term(value) else ""


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# --- chat ---------------------------------------------------------------------

CHAT_SYSTEM = (
    "You help someone shape one of their journeys - a CS degree and career, their "
    "health, or whatever it's for (stated below). A journey has several tracks "
    "(paths), each a list of steps placed in terms, plus a shared track for steps "
    "every track has in common. You see every track and step with its id, status "
    "and term. Keep advice true to what the journey is for.\n\n"
    "Talk with them: answer, compare tracks honestly when asked, ask a question when "
    "the request is unclear. You can't change anything yourself. When a change would "
    "help, propose it as an action; they accept or dismiss each one. Say 'I've "
    "proposed...' never 'I've done...' or 'I've added...' - nothing changes until "
    "they accept.\n\n"
    + TERM_RULES + "\n"
    "A journey laid out as a PATH MAP has no terms: leave term out, give a step a due date "
    "(YYYY-MM-DD) only when a date matters, and remember add_step puts it at the end of its track.\n\n"
    "Actions:\n"
    '- {"type": "add_step", "track_id": "...", "title": "...", "detail": "...", "term": "2027-winter"}\n'
    '- {"type": "set_status", "node_id": "...", "status": "proposed|accepted|done|rejected"}\n'
    '- {"type": "move_term", "node_id": "...", "term": "2027-spring"}\n'
    '- {"type": "set_note", "node_id": "...", "note": "..."}\n'
    '- {"type": "delete_step", "node_id": "..."}\n'
    '- {"type": "create_track", "name": "Research", "goal": "...", "steps": [{"title": "...", '
    '"detail": "...", "term": "2027-winter"}]} - steps are optional, up to 8; a new track has no '
    'id yet, so whenever they ask for a new track with steps, put those steps here rather than in add_step\n'
    '- {"type": "duplicate_track", "track_id": "...", "name": "Backup plan"}\n'
    '- {"type": "rename_track", "track_id": "...", "name": "..."}\n'
    '- {"type": "create_journey", "name": "Fitness", "purpose": "...", "folder": "Health"} - a whole '
    'new journey of its own, not a path in this one; folder is optional\n'
    '- {"type": "set_folder", "folder": "Health"} - put this journey in a folder ("" takes it out); '
    'reuse an existing folder name when one fits\n'
    '- {"type": "plan_step", "node_id": "...", "mode": "add|replace", "sub_steps": [{"title": "...", '
    '"detail": "...", "due": "2026-11-20"}]} - breaks one step into its own route of one-off things '
    "to do, in order. Use it when they ask how to do a step, what's involved, or to plan it out. "
    "3 to 8 sub-steps, each one sitting's work, starting with a verb (\"Draft resume bullets for "
    'Framelight", not "Resume"); detail says how in one line; due is an optional day between today '
    "and the end of the step's term, spaced out in order. A sub-step that should produce a number "
    "or answer they'll use later (a measurement, a score, a time, a choice, a link) carries "
    "\"needs\": what to record and \"unit\" - e.g. {\"title\": \"Measure your vertical\", \"needs\": "
    "\"Vertical jump\", \"unit\": \"in\"} - and can't be ticked off until they enter it. Only the one "
    "sub-step that actually tests it asks (a baseline, a re-test), never routine practice or daily goals. "
    "Later steps "
    "should build on recorded results. mode replace swaps out the sub-steps not "
    "done yet (done ones stay): use it when the step already has a plan and they ask to redo, "
    "change, shorten or reshape it. mode add appends: only for genuinely new extra pieces. Never "
    "repeat sub-steps it already has.\n"
    '- {"type": "add_daily_goal", "node_id" or "track_id" or "journey_id": "...", "name": "Apply to 2 '
    'internships", "per_week": 7} '
    "- a repeating goal they check off on each day they do it, shown in Habits too. Put it where it "
    "belongs: node_id when it only matters for that one step (\"film 3 practice jumps\" for a test), "
    "track_id when it serves the whole path (a warm-up, a training routine that carries on across "
    "steps), journey_id when it serves everything (sleep, stretching); on this journey's page leave all "
    "three out for the whole journey. Most routines belong to the path or journey, not one step. "
    "per_week is 7 for every day, or 1-6 times a week. Use it for anything they should do "
    "regularly rather than once (\"daily goals\", a routine, practice, a habit); one-off "
    "milestones are sub-steps instead. Up to 3 per turn, each small and countable.\n"
    '- add_step and edit_step can also carry "due": "2026-12-01", a date for the step\n'
    '- {"type": "set_layout", "journey_id": "...", "layout": "map|terms"} - draw a journey as a path '
    "map (ordered lines, no terms) or as school terms; only when they ask\n"
    '- {"type": "edit_step", "node_id": "...", "title": "...", "detail": "..."} - rename a step or '
    "rewrite its details; leave out what stays the same\n"
    '- {"type": "move_term", ...} can also carry "track_id" to move the step to another track\n'
    '- {"type": "edit_track", "track_id": "...", "name": "...", "goal": "..."} - rename a track or '
    "change what it aims at\n"
    '- {"type": "delete_track", "track_id": "..."} - a track and all its steps\n'
    '- {"type": "edit_journey", "journey_id": "...", "name": "...", "purpose": "..."} - rename a '
    "journey or change what it's for\n"
    '- {"type": "delete_journey", "journey_id": "..."} - a whole journey; only when they clearly ask\n'
    '- {"type": "edit_sub_step", "task_id": "...", "title": "...", "detail": "...", "due": '
    '"2026-11-20", "done": true, "needs": "Vertical jump", "unit": "in", "result": "18"} - change one '
    "sub-step; leave out what stays the same. A sub-step that asks for a result (needs) can't be done "
    "until it has one: when they tell you the number - or a rough answer like \"I can touch the rim\", "
    "which counts, never insist on an exact measurement - send result and done together\n"
    '- {"type": "delete_sub_step", "task_id": "..."}\n'
    '- {"type": "edit_daily_goal", "goal_id": "...", "name": "...", "per_week": 3} - can also carry '
    'node_id, track_id or journey_id to move it to a step, a path or the whole journey\n'
    '- {"type": "delete_daily_goal", "goal_id": "..."}\n'
    '- {"type": "remember", "fact": "Training for a half marathon in March"} - save a fact about '
    "them. Return it whenever they tell you something lasting about themselves (goals, school, "
    "work, health, preferences like the kind of internship they want, constraints, skills), even in "
    "passing and in the same turn as anything else, or ask you to remember it; one short sentence "
    "each, never something already listed\n"
    '- {"type": "edit_fact", "fact_no": 3, "fact": "..."} - correct a fact that changed\n'
    '- {"type": "forget", "fact_no": 3} - remove a fact\n'
    '- {"type": "set_term_note", "journey_id": "...", "term": "2026-fall", "note": "..."} - write '
    "what happened in a term (replaces that term's note, so keep what's there and add to it)\n"
    '- {"type": "log_daily_goal", "goal_id": "..."} - check off a daily goal for today\n'
    "If they ask for something none of these actions can do, say so plainly instead of claiming "
    "you proposed it.\n"
    "When they ask who they are or what you know about them, summarize the facts in a few "
    "plain sentences, then the journeys they're on.\n"
    "On this journey's page journey_id can be left out; it means this journey. To add one or two "
    "sub-steps use plan_step with mode add.\n"
    "If they say yes, accept or go ahead to changes already shown, don't propose them again - "
    "those are applied from the cards; reply in a few words.\n"
    'When a step is open, "this" means that step. When you propose a plan or daily goals, keep '
    "the reply to one or two sentences and don't list them - the card shows each one.\n"
    "Only use ids you were given. Step titles are six words or fewer, sub-step titles "
    "ten. Most turns need "
    "zero to three actions; a request to plan a whole track can use up to eight.\n\n"
    'Respond with JSON only: {"reply": "...", "actions": [...], "ask": {...} or null}'
)


@dataclass(frozen=True)
class JourneyAction:
    type: str
    label: str
    track_id: str = ""
    node_id: str = ""
    title: str = ""
    detail: str = ""
    term: str = ""
    status: str = ""
    note: str = ""
    name: str = ""
    goal: str = ""
    purpose: str = ""
    folder: str = ""
    steps: tuple = ()
    """For create_track: [{title, detail, term}] to put on the new track."""
    sub_steps: tuple = ()
    """For plan_step: [{title, detail, due}] to add inside the step."""
    mode: str = ""
    """For plan_step: "add" after the existing sub-steps, or "replace" the unfinished ones."""
    per_week: int = 0
    """For add_daily_goal / edit_daily_goal: 7 for every day, else times a week (0 = unchanged)."""
    journey_id: str = ""
    task_id: str = ""
    goal_id: str = ""
    due: str = ""
    """For edit_sub_step, add_step, edit_step: a YYYY-MM-DD date."""
    layout: str = ""
    """For set_layout: "terms" or "map"."""
    done: str = ""
    """For edit_sub_step: "yes" or "no" to tick or untick it, "" to leave it."""
    needs: str = ""
    """For edit_sub_step: what it asks them to record."""
    unit: str = ""
    result: str = ""
    """For edit_sub_step: the value they recorded."""
    fact: str = ""
    """For remember / edit_fact: the fact as it should read."""
    old_fact: str = ""
    """For edit_fact / forget: the fact as it read when proposed, so a
    later edit to the list can't make it change the wrong line."""


def _edits(a: dict, keys: tuple) -> str:
    """'rename to "X", due Nov 20, ...' for the fields an edit changes."""
    words = {"title": lambda v: f'rename to "{v}"', "name": lambda v: f'rename to "{v}"',
             "detail": lambda v: "new details", "goal": lambda v: f"goal: {v}",
             "purpose": lambda v: f"for: {v}", "due": lambda v: f"due {v}",
             "done": lambda v: "mark done" if v == "yes" else "mark not done",
             "per_week": lambda v: _how_often(v), "needs": lambda v: f"asks for {v}",
             "result": lambda v: f"result {v}"}
    return ", ".join(words[k](a[k]) for k in keys if a.get(k))


def _goal_target(a: dict) -> str:
    """Which field names where a daily goal goes: node_id, track_id, journey_id or ''."""
    return next((k for k in ("node_id", "track_id", "journey_id") if a.get(k)), "")


def _goal_place_ok(a: dict, ctx: JourneyContext) -> bool:
    """A daily goal's step, path or journey must be one shown. Leaving all
    out means this journey - for a new goal on a journey's own page; an
    edit leaving all out just doesn't move it."""
    target = _goal_target(a)
    known = {"node_id": ctx.node_titles, "track_id": ctx.track_ids, "journey_id": ctx.journey_ids}
    if target:
        return a[target] in known[target]
    return a["type"] == "edit_daily_goal" or not ctx.home


def _goal_place(a: dict, ctx: JourneyContext) -> str:
    target = _goal_target(a)
    if target == "node_id":
        return f'"{ctx.node_titles.get(a["node_id"], "that step")}"'
    if target == "track_id":
        name = ctx.track_ids.get(a["track_id"], "a")
        return f"the {name}" + ("" if name.lower().endswith("path") else " path")
    return ctx.journey_ids.get(a.get("journey_id", ""), "the whole journey")


def _label(a: dict, ctx: JourneyContext) -> str:
    step = f'"{ctx.node_titles.get(a.get("node_id", ""), "that step")}"'
    track = ctx.track_ids.get(a.get("track_id", ""), "a track")
    where = f" in {term_label(a['term'])}" if a.get("term") else ""
    journey = ctx.journey_ids.get(a.get("journey_id", ""), "this journey")
    in_journey = f" in {journey}" if ctx.home else ""
    # On the Journeys page, say which journey a step, path or goal is in.
    target = a.get("node_id") or a.get("track_id") or a.get("task_id") or a.get("goal_id")
    place = f" ({ctx.owner[target]})" if ctx.home and ctx.owner.get(target) else ""
    sub = f'sub-step "{ctx.task_titles.get(a.get("task_id", ""), "")}"'
    goal = f'daily goal "{ctx.goal_names.get(a.get("goal_id", ""), "")}"'
    return _base_label(a, ctx, step, track, where, journey, in_journey, sub, goal) + place


def _base_label(a, ctx, step, track, where, journey, in_journey, sub, goal) -> str:
    kind = a["type"]
    if kind == "move_term":
        to = (track if a.get("track_id") else "") + (" · " if a.get("track_id") and a.get("term") else "")
        return f"Move {step} to {to}{term_label(a['term']) if a.get('term') else ''}"
    return {
        "add_step": f'Add "{a.get("title")}" to {track}{where}' + (f", due {a['due']}" if a.get("due") else ""),
        "set_status": f"Mark {step} {a.get('status')}",
        "set_note": f"Note on {step}: {a.get('note')}",
        "delete_step": f"Delete {step}",
        "create_track": f'New track "{a.get("name")}"{in_journey}'
                        + (f' with {len(a["steps"])} steps' if a.get("steps") else ""),
        "duplicate_track": f'Copy {track} as "{a.get("name")}"',
        "rename_track": f'Rename {track} to "{a.get("name")}"',
        "create_journey": f'New journey "{a.get("name")}"'
                          + (f' in folder "{a["folder"]}"' if a.get("folder") else ""),
        "set_layout": f"Show {journey} as {LAYOUT_WORDS.get(a.get('layout'), '')}",
        "set_folder": (f'Put {journey} in folder "{a.get("folder")}"' if a.get("folder")
                       else f"Take {journey} out of its folder"),
        "plan_step": (f"Redo the plan for {step}: {len(a['sub_steps'])} sub-steps"
                      + (f" (replaces {ctx.unfinished[a['node_id']]} unfinished)"
                         if ctx.unfinished.get(a["node_id"]) else "")
                      if a["mode"] == "replace" else f"Plan {step}: {len(a['sub_steps'])} sub-steps"),
        "add_daily_goal": f"Daily goal for {_goal_place(a, ctx)}: {a.get('name')} ({_how_often(a['per_week'])})",
        "edit_step": f"Step {step}: " + _edits(a, ("title", "detail", "due")),
        "edit_track": f"Path {track}: " + _edits(a, ("name", "goal")),
        "delete_track": f"Delete the {track} path and its steps",
        "edit_journey": f"Journey {journey}: " + _edits(a, ("name", "purpose")),
        "delete_journey": f"Delete the journey {journey} and everything in it",
        "edit_sub_step": f"{sub[0].upper()}{sub[1:]}: " + _edits(a, ("title", "detail", "due", "needs", "result", "done")),
        "delete_sub_step": f"Delete {sub}",
        "edit_daily_goal": f"{goal[0].upper()}{goal[1:]}: " + ", ".join(
            x for x in (_edits(a, ("name", "per_week")),
                        "move to " + _goal_place(a, ctx) if _goal_target(a) else "") if x),
        "delete_daily_goal": f"Delete {goal}",
        "remember": f"Remember: {a.get('fact')}",
        "edit_fact": f'Change "{a.get("old_fact")}" to "{a.get("fact")}"',
        "forget": f'Forget "{a.get("old_fact")}"',
        "set_term_note": f"Note for {term_label(a['term']) if a.get('term') else 'a term'}{in_journey}: "
                         f"{a.get('note')}",
        "log_daily_goal": f"Check off {goal} for today",
    }[kind]


def _starting_steps(raw) -> tuple:
    steps = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and _text(item.get("title"), 80):
            steps.append({"title": _text(item.get("title"), 80), "detail": _text(item.get("detail"), 400),
                          "term": _term(item.get("term"))})
    return tuple(steps[:MAX_ACTIONS])


def _sub_steps(raw) -> tuple:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and _text(item.get("title"), 120):
            out.append({"title": _text(item.get("title"), 120), "detail": _text(item.get("detail"), 300),
                        "due": clean_due(item.get("due")), "needs": _text(item.get("needs"), 60),
                        "unit": _text(item.get("unit"), 20)})
    return tuple(out[:MAX_SUB_STEPS])


def _per_week(value) -> int:
    try:
        return min(7, max(1, int(value)))
    except (TypeError, ValueError):
        return 7


def _done(value) -> str:
    if value in (True, "yes", "true"):
        return "yes"
    if value in (False, "no", "false"):
        return "no"
    return ""


def _clean_action(item, ctx: JourneyContext) -> JourneyAction | None:
    if not isinstance(item, dict) or item.get("type") not in ACTION_TYPES:
        return None
    kind = item["type"]
    a = {
        "type": kind,
        "track_id": str(item.get("track_id", "")),
        "node_id": str(item.get("node_id", "")),
        "title": _text(item.get("title"), 120 if kind == "edit_sub_step" else 80),
        "detail": _text(item.get("detail"), 400),
        "term": _term(item.get("term")),
        "status": str(item.get("status", "")),
        "note": _text(item.get("note"), 400),
        "name": _text(item.get("name"), 40),
        "goal": _text(item.get("goal"), 160),
        "purpose": _text(item.get("purpose"), 500),
        "folder": _text(item.get("folder"), 40),
        "steps": _starting_steps(item.get("steps")) if kind == "create_track" else (),
        "sub_steps": _sub_steps(item.get("sub_steps")) if kind == "plan_step" else (),
        "mode": "replace" if kind == "plan_step" and item.get("mode") == "replace" else
                ("add" if kind == "plan_step" else ""),
        "per_week": _per_week(item.get("per_week")) if kind == "add_daily_goal" or
                    (kind == "edit_daily_goal" and item.get("per_week")) else 0,
        "journey_id": str(item.get("journey_id", "")),
        "task_id": str(item.get("task_id", "")),
        "goal_id": str(item.get("goal_id", "")),
        "due": clean_due(item.get("due")) if kind in ("edit_sub_step", "add_step", "edit_step") else "",
        "layout": str(item.get("layout", "")) if kind == "set_layout" else "",
        "done": _done(item.get("done")) if kind == "edit_sub_step" else "",
        "needs": _text(item.get("needs"), 60) if kind == "edit_sub_step" else "",
        "unit": _text(item.get("unit"), 20) if kind == "edit_sub_step" else "",
        "result": _text(item.get("result"), 200) if kind == "edit_sub_step" else "",
        "fact": _text(item.get("fact"), 300),
        "old_fact": _old_fact(item, ctx),
    }
    return JourneyAction(label=_label(a, ctx), **a) if _valid(a, ctx) else None


def _old_fact(item: dict, ctx: JourneyContext) -> str:
    """The fact an edit_fact / forget points at, by number (or the text it
    already carries, when a saved proposal is re-checked)."""
    if item.get("type") not in ("edit_fact", "forget"):
        return ""
    if item.get("old_fact") in ctx.facts:
        return item["old_fact"]
    try:
        n = int(item.get("fact_no"))
    except (TypeError, ValueError):
        return ""
    return ctx.facts[n - 1] if 1 <= n <= len(ctx.facts) else ""


def _valid(a: dict, ctx: JourneyContext) -> bool:
    kind = a["type"]
    if kind in ("remember", "edit_fact") and not a["fact"]:
        return False
    if kind in ("edit_fact", "forget") and not a["old_fact"]:
        return False
    if kind == "remember" and a["fact"] in ctx.facts:
        return False
    if kind in ("set_status", "move_term", "set_note", "delete_step", "plan_step",
                "edit_step") and a["node_id"] not in ctx.node_titles:
        return False
    if kind in ("add_daily_goal", "edit_daily_goal") and not _goal_place_ok(a, ctx):
        return False
    if kind in ("add_step", "duplicate_track", "rename_track", "edit_track", "delete_track") \
            and a["track_id"] not in ctx.track_ids:
        return False
    if kind == "move_term" and a["track_id"] and a["track_id"] not in ctx.track_ids:
        return False
    if kind in ("edit_sub_step", "delete_sub_step") and a["task_id"] not in ctx.task_titles:
        return False
    if kind == "set_term_note" and not (a["term"] and a["note"]):
        return False
    if kind == "set_layout" and a["layout"] not in LAYOUT_WORDS:
        return False
    if kind in ("edit_daily_goal", "delete_daily_goal", "log_daily_goal") and a["goal_id"] not in ctx.goal_names:
        return False
    # On a journey's own page journey_id may be left out (it means that
    # journey); on the Journeys page it has to name one.
    if kind in JOURNEY_LEVEL and (a["journey_id"] or ctx.home) and a["journey_id"] not in ctx.journey_ids:
        return False
    if kind == "plan_step" and not a["sub_steps"]:
        return False
    if kind == "add_step" and not a["title"]:
        return False
    if kind == "set_status" and a["status"] not in STATUSES:
        return False
    if kind == "move_term" and not (a["term"] or a["track_id"]):
        return False
    if kind in ("create_track", "duplicate_track", "rename_track", "create_journey",
                "add_daily_goal") and not a["name"]:
        return False
    nothing = {"edit_step": ("title", "detail", "due"), "edit_track": ("name", "goal"),
               "edit_journey": ("name", "purpose"),
               "edit_sub_step": ("title", "detail", "due", "done", "needs", "unit", "result"),
               "edit_daily_goal": ("name", "per_week", "node_id", "track_id", "journey_id")}
    if kind in nothing and not any(a[k] for k in nothing[kind]):
        return False
    if kind == "create_track" and not a["goal"]:
        a["goal"] = a["name"]
    return True


def revise_action(action: dict, ctx: JourneyContext) -> JourneyAction | None:
    """Re-check and re-label a proposal after the user edited it."""
    return _clean_action(action, ctx)


# The model sometimes says "I've added X" for a change that only happens on
# Accept. When the reply carries proposals, reword those claims to match.
_DONE_TO_PROPOSED = {
    "added": "adding", "moved": "moving", "deleted": "deleting", "removed": "removing",
    "created": "creating", "made": "making", "updated": "updating", "changed": "changing",
    "marked": "marking", "set": "setting", "put": "putting", "renamed": "renaming",
}
_DONE_CLAIM = re.compile(r"\bI(?:'ve| have)? (" + "|".join(_DONE_TO_PROPOSED) + r")\b")


def _as_proposal(reply: str) -> str:
    return _DONE_CLAIM.sub(lambda m: "I've proposed " + _DONE_TO_PROPOSED[m.group(1)], reply)


# Changes that always wait for the user's OK, even when the rest apply at once.
ASKS_FIRST = ("delete_step", "delete_track", "delete_journey", "delete_sub_step", "delete_daily_goal",
              "forget")


def parse_chat(text: str, ctx: JourneyContext, auto: bool = False) -> tuple[str, list[JourneyAction]]:
    """auto: the changes (other than ASKS_FIRST) are applied as soon as
    they come back, so a reply saying "I've added" is true."""
    data = extract_json_object(text)
    reply = str(data.get("reply", "")).strip()
    if not reply:
        raise ValueError("no reply text in journey chat output")
    raw = data.get("actions", [])
    actions = [a for a in (_clean_action(i, ctx) for i in (raw if isinstance(raw, list) else []))
               if a is not None]
    claims_done = actions and not (auto and all(a.type not in ASKS_FIRST for a in actions))
    return (_as_proposal(reply) if claims_done else reply), actions[:MAX_ACTIONS]


HOME_RULES = (
    "\n\nThey are on the Journeys page and you see every journey, each with its id. Any action "
    "can touch any journey: step, track, sub-step and goal ids already say which journey they are "
    "in. create_track, set_folder, edit_journey and delete_journey must carry the journey_id. "
    "Folders group journeys; reuse an existing folder name when one fits."
)


ASK_INPUTS = ("number", "text", "date")
MAX_CHOICES = 6


def parse_ask(text: str) -> dict | None:
    """The one question the assistant wants answered next, if any:
    {question, choices, input, unit}. Choices are tappable answers; input
    is the kind of box for typing their own."""
    raw = extract_json_object(text).get("ask")
    if not isinstance(raw, dict) or not _text(raw.get("question"), 200):
        return None
    choices = [c for c in (_text(c, 60) for c in (raw.get("choices") or [])
                           if isinstance(raw.get("choices"), list)) if c]
    kind = str(raw.get("input") or "")
    return {"question": _text(raw.get("question"), 200), "choices": choices[:MAX_CHOICES],
            "input": kind if kind in ASK_INPUTS else ("" if choices else "text"),
            "unit": _text(raw.get("unit"), 20)}


GUIDE_RULES = (
    "\n\nBE A RELAXED COACH, NOT A FORM. Short, friendly sentences; one thing at a time.\n"
    "When they start something (\"help me get started on...\", \"walk me through...\"), first find out "
    "what you need to plan it well - where they are now (a number, a level), what they have, how much "
    "time - by asking ONE question per turn in \"ask\": {\"question\": \"...\", \"choices\": [up to 5 "
    "short answers, ending with \"I'm not sure\"], \"input\": \"number|text|date\" when they might type "
    "their own answer, \"unit\": \"inches\"}. Put only a line or two in reply when you ask; the card shows "
    "the choices. Don't plan in the same turn you ask, and ask at most 3 questions before planning.\n"
    "If they're not sure, explain in 2-4 short numbered lines how to find out with what they have at "
    "home, then ask again with an input box so they can type what they got.\n"
    "When they answer with something lasting about themselves (a measurement, a level, gear they own, "
    "how much time they have), return a remember action for it IN THAT SAME TURN - even while you ask "
    "the next question - written as a fact with the month, like \"Vertical jump: 22 in (Nov 2026)\".\n"
    "Then plan the route with plan_step, built on their answers: each sub-step a small tutorial step "
    "whose detail says exactly how, in plain words.\n"
    "When they ask you to walk them through one sub-step, coach it live: give the first small thing to "
    "do, ask how it went (with choices), then the next. Mark the sub-step done with edit_sub_step when "
    "they say they finished it.\n"
    "BEFORE YOU PLAN OR SUGGEST: when they ask you to plan a step, redo a plan, or suggest daily goals, "
    "first check WHAT THEY'VE TOLD YOU (their saved facts). If those don't answer something that would "
    "change the plan - for internships, which kind of role (and when, where); for training, where "
    "they're at now - ask ONE question in \"ask\" before planning, at most 2 in all. Saved documents "
    "and notes can be out of date, so use them to offer the likely answers as choices (\"Still AI/ML "
    "agent or eval roles?\") rather than assuming. Return a remember action for their answer, so next "
    "time you don't ask. If their facts already answer it, don't ask: plan, and say in a few words "
    "what you based it on.\n"
    "Make plans and suggestions theirs, not generic: name their real projects, courses, numbers, "
    "preferences and deadlines from what you know. When they've recorded a result, build the rest of "
    "the route from it."
)


# Built from an answer, so dropped from a reply that's still asking the question.
PLANS_WAIT_FOR_ANSWER = ("plan_step", "add_daily_goal", "add_step")

# Said last, next to the message, where the model weighs it most.
PERSONAL_REMINDER = (
    "\n\n(Make your answer theirs: use their facts and the documents above where they fit - "
    "e.g. the kind of role they want, their real projects - and say in a few words what you "
    "went on. If this is a plan or suggestions and their saved facts don't yet say something that "
    "would change it, ask that one question first, offering choices from the documents.)"
)


AUTO_RULES = (
    "\n\nRIGHT NOW THEIR CHANGES APPLY AT ONCE: every action you return is made as soon as you "
    "answer, except deletions and forget, which wait for their OK. So when they ask for something, "
    "just do it - return the actions and say what you did (\"I've added...\"); for a deletion say "
    "you've proposed it. Don't ask permission for anything that isn't a deletion. Asking for something "
    "you need before planning (BEFORE YOU PLAN above) isn't asking permission - still do that."
)


def journey_chat(llm: LLMClient, ctx: JourneyContext, history: list[dict],
                 message: str, auto: bool = False, notes: str = "") -> tuple[str, list[JourneyAction], dict | None]:
    """One turn: the reply, the changes it makes, and the question it
    wants answered next (or None). notes: extra background for this turn
    (their matching documents)."""
    if not message.strip():
        raise ValueError("message must not be empty")
    convo = "\n".join(f"{str(h.get('role', 'user')).upper()}: {h.get('content', '')}"
                      for h in history[-12:])
    prompt = ctx.text + notes + ("\n\nCONVERSATION SO FAR:\n" + convo if convo else "") + f"\n\nUSER: {message}"
    if notes:
        prompt += PERSONAL_REMINDER
    system = CHAT_SYSTEM + GUIDE_RULES + (HOME_RULES if ctx.home else "") + (AUTO_RULES if auto else "")
    text = llm.complete(system, prompt, max_tokens=CHAT_MAX_TOKENS).text
    reply, actions = parse_chat(text, ctx, auto)
    ask = parse_ask(text)
    if ask:   # a question comes before the plan it's for: hold the plan until it's answered
        actions = [a for a in actions if a.type not in PLANS_WAIT_FOR_ANSWER]
    return reply, actions, ask


# --- year review ----------------------------------------------------------------

REVIEW_SYSTEM = (
    "You review one past school year of a CS student's journey. You get their own "
    "notes on what they did each term, and their tracks (career goals) with the steps "
    "planned so far.\n\n"
    "Be honest and specific, like a good mentor: credit what actually moved them "
    "toward their goals, name what didn't, and name gaps compared with a typical "
    "strong path toward each goal. Use only what their notes say happened; never "
    "invent accomplishments. Steps shown as planned or suggested "
    "are plans, not things they did - only their notes and steps shown as done count "
    "as having happened. Never propose a step that is already listed. If the notes are thin, say what's missing.\n\n"
    + TERM_RULES + "\n\n"
    "Return JSON only:\n"
    '{"summary": "3-5 sentences",\n'
    ' "went_well": ["..."], "gaps": ["..."],\n'
    ' "tracks": [{"track_id": "...", "verdict": "one or two sentences on this track"}],\n'
    ' "done_steps": [{"title": "six words or fewer", "detail": "...", "term": "2025-fall"}],\n'
    ' "next_steps": [{"track_id": "...", "title": "...", "detail": "why, in one sentence", '
    '"term": "a term from now on"}]}\n'
    "done_steps turns what they did into finished steps (only things their notes say "
    "they did, each in the term it happened): group related things, so a term's "
    "classes are one step and at most 6 steps in all, and no step for a term with nothing to report. next_steps are concrete "
    "changes for the coming terms - at most 2 per track, plus the shared track id "
    "for up to 2 steps every track needs."
)


def review_year(llm: LLMClient, ctx: JourneyContext, year: int, terms: list[str],
                reflections: dict[str, str], now_term: str) -> dict:
    notes = "\n".join(f"{term_label(t)} ({t}): {reflections.get(t, '').strip() or '(nothing written)'}"
                      for t in terms)
    if not any(reflections.get(t, "").strip() for t in terms):
        raise ValueError(f"Write a few lines about Year {year} in its terms first")
    prompt = f"{ctx.text}\n\nYEAR {year} - THEIR NOTES, TERM BY TERM:\n{notes}"
    data = extract_json_object(llm.complete(REVIEW_SYSTEM, prompt, max_tokens=REVIEW_MAX_TOKENS).text)
    return parse_review(data, ctx, set(terms), now_term)


def _strings(value, limit: int = 8) -> list[str]:
    return [_text(v, 300) for v in (value if isinstance(value, list) else []) if _text(v, 300)][:limit]


def parse_review(data: dict, ctx: JourneyContext, year_terms: set[str], now_term: str) -> dict:
    done = []
    for item in data.get("done_steps", []) if isinstance(data.get("done_steps"), list) else []:
        if not isinstance(item, dict) or not _text(item.get("title"), 80):
            continue
        term = _term(item.get("term"))
        done.append({"title": _text(item.get("title"), 80), "detail": _text(item.get("detail"), 400),
                     "term": term if term in year_terms else ""})
    nxt = []
    for item in data.get("next_steps", []) if isinstance(data.get("next_steps"), list) else []:
        if not isinstance(item, dict) or not _text(item.get("title"), 80):
            continue
        term = _term(item.get("term"))
        if term and term_rank(term) < term_rank(now_term):
            term = now_term
        track = str(item.get("track_id", ""))
        nxt.append({"track_id": track if track in ctx.track_ids else "",
                    "title": _text(item.get("title"), 80),
                    "detail": _text(item.get("detail"), 400), "term": term})
    verdicts = [{"track_id": str(t.get("track_id")), "track": ctx.track_ids[str(t.get("track_id"))],
                 "verdict": _text(t.get("verdict"), 400)}
                for t in (data.get("tracks") if isinstance(data.get("tracks"), list) else [])
                if isinstance(t, dict) and str(t.get("track_id")) in ctx.track_ids and t.get("verdict")]
    summary = _text(data.get("summary"), 1500)
    if not summary:
        raise ValueError("the review came back empty - try again")
    return {"summary": summary, "went_well": _strings(data.get("went_well")),
            "gaps": _strings(data.get("gaps")), "tracks": verdicts,
            "done_steps": done[:MAX_SUGGESTIONS], "next_steps": nxt[:MAX_SUGGESTIONS]}


# --- evidence -------------------------------------------------------------------

EVIDENCE_SYSTEM = (
    "You keep a CS student's journey up to date from evidence: things from their "
    "own records ({source}). Each item has a date.\n\n"
    "Match evidence to the journey. Propose:\n"
    '- {{"kind": "mark_done", "node_id": "...", "reason": "which evidence shows it"}} when '
    "a planned step is clearly finished;\n"
    '- {{"kind": "add_done", "track_id": "...", "title": "...", "detail": "...", "term": "...", '
    '"reason": "..."}} for real progress not on the journey yet (a course covered, a '
    "project shipped, an interview, a club joined), placed in the term it happened;\n"
    '- {{"kind": "add_step", "track_id": "...", "title": "...", "detail": "...", "term": "...", '
    '"reason": "..."}} for a clear next step the evidence points to (a deadline, a '
    "follow-up).\n"
    "Be selective: group many small items into one meaningful step (twenty chats "
    "about data structures are one step, 'Data structures: vector vs list, hashing'), "
    "skip trivia and anything unrelated to their goals, never invent. Use the shared "
    "track id for general CS progress. Titles six words or fewer.\n\n"
    + TERM_RULES + "\n\n"
    'Return JSON only: {{"suggestions": [...]}}, at most 10, empty if nothing qualifies.'
)

SOURCE_NAMES = {
    "mindtrail": "their Mind Trail practice log, job applications, interviews and chats",
    "gmail": "their recent email",
    "calendar": ("their Google Calendar events for the next two months (these are upcoming, so "
                 "propose steps placed in the term of the event date, never mark anything done)"),
    "gemini": "their questions to Google Gemini",
    "paste": "a chat they pasted in",
}


def find_evidence(llm: LLMClient, ctx: JourneyContext, source: str, items: list[str]) -> list[dict]:
    if not items:
        return []
    system = EVIDENCE_SYSTEM.format(source=SOURCE_NAMES.get(source, source))
    prompt = f"{ctx.text}\n\nEVIDENCE:\n" + "\n".join(f"- {i}" for i in items)
    data = extract_json_object(llm.complete(system, prompt, max_tokens=EVIDENCE_MAX_TOKENS).text)
    return parse_evidence(data, ctx)


def parse_evidence(data: dict, ctx: JourneyContext) -> list[dict]:
    out = []
    raw = data.get("suggestions", [])
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        reason = _text(item.get("reason"), 300)
        if kind == "mark_done":
            node_id = str(item.get("node_id", ""))
            if node_id in ctx.node_titles:
                out.append({"kind": kind, "node_id": node_id, "title": ctx.node_titles[node_id],
                            "detail": "", "term": "", "track_id": "", "reason": reason})
        elif kind in ("add_done", "add_step") and _text(item.get("title"), 80):
            track = str(item.get("track_id", ""))
            out.append({"kind": kind, "node_id": "", "title": _text(item.get("title"), 80),
                        "detail": _text(item.get("detail"), 400), "term": _term(item.get("term")),
                        "track_id": track if track in ctx.track_ids else "", "reason": reason})
    return out[:MAX_SUGGESTIONS]
