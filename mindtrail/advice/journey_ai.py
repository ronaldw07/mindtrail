"""The model's three jobs on the journey: chat that proposes changes,
a review of a past year, and matching outside evidence to steps.

Like advice/roadmap_chat.py, none of this writes anything. Each function
returns proposals; the caller shows them and applies only what you
accept. Every id and term the model sends back is checked against the
real journey, and anything that doesn't check out is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mindtrail.advice.json_reply import extract_json_object
from mindtrail.llm import LLMClient
from mindtrail.organize.roadmaps import STATUSES
from mindtrail.organize.terms import is_term, term_label, term_rank

CHAT_MAX_TOKENS = 2500
REVIEW_MAX_TOKENS = 4000
EVIDENCE_MAX_TOKENS = 3000
MAX_ACTIONS = 8
MAX_SUGGESTIONS = 12

# What the model sees for each status, so "accepted" can't be read as "finished".
STATUS_WORDS = {"accepted": "planned", "proposed": "suggested", "done": "done", "rejected": "skipped"}

ACTION_TYPES = ("add_step", "set_status", "move_term", "set_note", "delete_step",
                "create_track", "duplicate_track", "rename_track")

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


def build_context(start_year: int, current_term: str, shared, tracks: list,
                  steps_by_track: dict[str, list], profile: str = "") -> JourneyContext:
    lines = [
        f"JOURNEY: a 4-year CS degree, Year 1 starting fall {start_year}.",
        f"CURRENT TERM: {current_term} ({term_label(current_term)}).",
    ]
    if profile.strip():
        lines.append(f"USER PROFILE:\n{profile.strip()[:1500]}")
    track_ids, node_titles = {}, {}
    for track in ([shared] if shared else []) + list(tracks):
        is_shared = shared is not None and track.id == shared.id
        label = "SHARED (shown on every track)" if is_shared else f"TRACK {track.name or track.goal}"
        lines.append(f"\n{label} id={track.id} goal: {track.goal}")
        track_ids[track.id] = track.name or track.goal
        steps = steps_by_track.get(track.id, [])
        if not steps:
            lines.append("  (no steps yet)")
        for n in steps:
            node_titles[n.id] = n.title
            line = f"  - id={n.id} [{STATUS_WORDS.get(n.status, n.status)}] {n.term or 'no term'}: {n.title}"
            if n.detail:
                line += f" - {n.detail[:160]}"
            if n.note:
                line += f" (note: {n.note[:160]})"
            lines.append(line)
    return JourneyContext("\n".join(lines), track_ids, node_titles)


def _term(value) -> str:
    value = str(value or "").strip().lower()
    return value if is_term(value) else ""


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# --- chat ---------------------------------------------------------------------

CHAT_SYSTEM = (
    "You help a CS student shape their 4-year journey: several career tracks, each "
    "a list of steps placed in school terms, plus a shared track for steps every "
    "track has in common. You see every track and step with its id, status and term.\n\n"
    "Talk with them: answer, compare tracks honestly when asked, ask a question when "
    "the request is unclear. You can't change anything yourself. When a change would "
    "help, propose it as an action; they accept or dismiss each one. Say 'I've "
    "proposed...' never 'I've done...'.\n\n"
    + TERM_RULES + "\n\n"
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
    "Only use ids you were given. Titles are six words or fewer. Most turns need "
    "zero to three actions; a request to plan a whole track can use up to eight.\n\n"
    'Respond with JSON only: {"reply": "...", "actions": [...]}'
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
    steps: tuple = ()
    """For create_track: [{title, detail, term}] to put on the new track."""


def _label(a: dict, ctx: JourneyContext) -> str:
    step = f'"{ctx.node_titles.get(a.get("node_id", ""), "that step")}"'
    track = ctx.track_ids.get(a.get("track_id", ""), "a track")
    where = f" in {term_label(a['term'])}" if a.get("term") else ""
    return {
        "add_step": f'Add "{a.get("title")}" to {track}{where}',
        "set_status": f"Mark {step} {a.get('status')}",
        "move_term": f"Move {step} to {term_label(a['term'])}" if a.get("term") else "",
        "set_note": f"Note on {step}: {a.get('note')}",
        "delete_step": f"Delete {step}",
        "create_track": f'New track "{a.get("name")}"'
                        + (f' with {len(a["steps"])} steps' if a.get("steps") else ""),
        "duplicate_track": f'Copy {track} as "{a.get("name")}"',
        "rename_track": f'Rename {track} to "{a.get("name")}"',
    }[a["type"]]


def _starting_steps(raw) -> tuple:
    steps = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and _text(item.get("title"), 80):
            steps.append({"title": _text(item.get("title"), 80), "detail": _text(item.get("detail"), 400),
                          "term": _term(item.get("term"))})
    return tuple(steps[:MAX_ACTIONS])


def _clean_action(item, ctx: JourneyContext) -> JourneyAction | None:
    if not isinstance(item, dict) or item.get("type") not in ACTION_TYPES:
        return None
    a = {
        "type": item["type"],
        "track_id": str(item.get("track_id", "")),
        "node_id": str(item.get("node_id", "")),
        "title": _text(item.get("title"), 80),
        "detail": _text(item.get("detail"), 400),
        "term": _term(item.get("term")),
        "status": str(item.get("status", "")),
        "note": _text(item.get("note"), 400),
        "name": _text(item.get("name"), 40),
        "goal": _text(item.get("goal"), 160),
        "steps": _starting_steps(item.get("steps")) if item["type"] == "create_track" else (),
    }
    kind = a["type"]
    if kind in ("set_status", "move_term", "set_note", "delete_step") and a["node_id"] not in ctx.node_titles:
        return None
    if kind in ("add_step", "duplicate_track", "rename_track") and a["track_id"] not in ctx.track_ids:
        return None
    if kind == "add_step" and not a["title"]:
        return None
    if kind == "set_status" and a["status"] not in STATUSES:
        return None
    if kind == "move_term" and not a["term"]:
        return None
    if kind in ("create_track", "duplicate_track", "rename_track") and not a["name"]:
        return None
    if kind == "create_track" and not a["goal"]:
        a["goal"] = a["name"]
    return JourneyAction(label=_label(a, ctx), **a)


def parse_chat(text: str, ctx: JourneyContext) -> tuple[str, list[JourneyAction]]:
    data = extract_json_object(text)
    reply = str(data.get("reply", "")).strip()
    if not reply:
        raise ValueError("no reply text in journey chat output")
    raw = data.get("actions", [])
    actions = [a for a in (_clean_action(i, ctx) for i in (raw if isinstance(raw, list) else []))
               if a is not None]
    return reply, actions[:MAX_ACTIONS]


def journey_chat(llm: LLMClient, ctx: JourneyContext, history: list[dict],
                 message: str) -> tuple[str, list[JourneyAction]]:
    if not message.strip():
        raise ValueError("message must not be empty")
    convo = "\n".join(f"{str(h.get('role', 'user')).upper()}: {h.get('content', '')}"
                      for h in history[-12:])
    prompt = ctx.text + ("\n\nCONVERSATION SO FAR:\n" + convo if convo else "") + f"\n\nUSER: {message}"
    return parse_chat(llm.complete(CHAT_SYSTEM, prompt, max_tokens=CHAT_MAX_TOKENS).text, ctx)


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
        raise ValueError(f"write a few lines about Year {year} first")
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
