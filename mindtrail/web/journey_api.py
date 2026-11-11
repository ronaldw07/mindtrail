"""Handlers for journeys (organize/journey.py).

Every handler works on the open journey. `handle_get` returns the whole
of it in one response - plus the list of all journeys for the switcher - tracks, steps,
the year/term grid, reflections, reviews, pending suggestions and what's
next - so the Timeline re-renders from a single fetch after any change.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta

from mindtrail.advice import journey_ai
from mindtrail.advice.assistant_context import document_notes, with_attachments
from mindtrail.integrations.calendar_events import CalendarEvents
from mindtrail.integrations.calendar_write import create_event
from mindtrail.integrations.gemini_takeout import parse_takeout
from mindtrail.integrations.google_api import GoogleAuthError, GoogleFetchError
from mindtrail.llm import LLMError
from mindtrail.organize.journey import YEARS, layout_of
from mindtrail.organize.profile import MAX_PROFILE_CHARS
from mindtrail.organize.step_tasks import clean_due
from mindtrail.organize.roadmaps import SHARED_KIND, duplicate_roadmap
from mindtrail.organize.terms import (
    next_term, term_label, term_of, term_rank, year_of, year_terms,
)
from mindtrail.web.life_api import STREAK_LOOKBACK_DAYS, habit_json

NEXT_UP = 3
STATUS_ORDER = {"accepted": 0, "proposed": 1, "done": 2, "rejected": 3}
EVIDENCE_DAYS = 400
MAX_EVIDENCE_ITEMS = 150
MAX_GEMINI_PROMPTS = 150
MAX_PASTE = 12000
GMAIL_QUERY = ("-category:promotions -category:social (hackathon OR research OR club OR "
               "accepted OR welcome OR enrolled OR enrollment OR fellowship OR scholarship OR "
               "internship OR interview OR offer OR program OR certificate)")
GMAIL_LIMIT = 40
GMAIL_DAYS = 120
CALENDAR_DAYS = 60
GEMINI_STATE_KEY = "journey_gemini_through"


def _try(fn):
    try:
        return fn()
    except (ValueError, LLMError) as exc:
        return {"error": str(exc)}
    except (TypeError, AttributeError, KeyError):   # a malformed request body
        return {"error": "that request wasn't in the expected shape"}


def _step_json(n, track_id: str, progress: tuple = (0, 0)) -> dict:
    return {"id": n.id, "track_id": track_id, "title": n.title, "detail": n.detail,
            "status": n.status, "note": n.note, "term": n.term, "due_date": n.due_date,
            "position": n.position, "created_at": n.created_at, "progress": list(progress)}


def _track_json(r, steps: list, progress: dict | None = None) -> dict:
    ordered = sorted(steps, key=lambda n: (STATUS_ORDER.get(n.status, 1), n.created_at))
    progress = progress or {}
    return {"id": r.id, "name": r.name or r.goal, "goal": r.goal, "shared": r.kind == SHARED_KIND,
            "steps": [_step_json(n, r.id, progress.get(n.id, (0, 0))) for n in ordered]}


def _grid(start_year: int, now: str) -> list[dict]:
    years = []
    for number in range(1, YEARS + 1):
        terms = [{"term": t, "label": term_label(t), "season": t.split("-")[1],
                  "past": term_rank(t) < term_rank(now), "current": t == now}
                 for t in year_terms(start_year, number)]
        years.append({"number": number, "label": f"Year {number}",
                      "span": f"{start_year + number - 1}–{str(start_year + number)[2:]}",
                      "terms": terms})
    return years


def next_up(tracks: list[dict], now: str) -> list[dict]:
    """The few steps worth doing first: anything left over from a past
    term, then this term's, then next term's - accepted before proposed."""
    soon = term_rank(next_term(now))
    names = {t["id"]: t["name"] for t in tracks}
    picks = []
    for track in tracks:
        for s in track["steps"]:
            if s["status"] in ("done", "rejected") or not s["term"]:
                continue
            rank = term_rank(s["term"])
            if rank > soon:
                continue
            if rank < term_rank(now):
                reason, tier = f"Left over from {term_label(s['term'])}", 0
            elif rank == term_rank(now):
                reason, tier = "This term", 1
            else:
                reason, tier = "Next term - worth starting now", 2
            if s["status"] == "proposed":
                reason += " · not accepted yet"
            picks.append((tier, STATUS_ORDER[s["status"]], rank,
                          {**s, "track": names[s["track_id"]], "reason": reason}))
    picks.sort(key=lambda p: p[:3])
    return [p[3] for p in picks[:NEXT_UP]]


def _in_order(steps: list[dict]) -> list[dict]:
    """A path map's steps, first to last."""
    return sorted(steps, key=lambda s: (s["position"], s["created_at"]))


def next_on_paths(tracks: list[dict]) -> list[dict]:
    """On a path map: the first step not done yet on each path, soonest
    date first."""
    picks = []
    for track in tracks:
        step = next((s for s in _in_order(track["steps"]) if s["status"] not in ("done", "rejected")), None)
        if step is None:
            continue
        reason = "Next stop" + (f" · by {step['due_date']}" if step["due_date"] else "")
        if step["status"] == "proposed":
            reason += " · not accepted yet"
        picks.append((step["due_date"] or "9999", {**step, "track": track["name"], "reason": reason}))
    picks.sort(key=lambda p: p[0])
    return [p[1] for p in picks[:NEXT_UP]]


def _next(tracks: list[dict], layout: str, now: str) -> list[dict]:
    return next_on_paths(tracks) if layout == "map" else next_up(tracks, now)


def _suggestion_json(s, names: dict) -> dict:
    return {**asdict(s), "track": names.get(s.roadmap_id, ""),
            "term_label": term_label(s.term) if s.term else ""}


def _candidates(projects, roadmaps, nodes) -> list[dict]:
    """Roadmaps in other projects that setup can copy in as a track."""
    out = []
    for p in projects.all():
        for r in roadmaps.list_for_project(p.id):
            out.append({"roadmap_id": r.id, "project": p.name, "goal": r.goal,
                        "steps": len(nodes.for_roadmap(r.id))})
    return out


NEXT_PER_BOX = 3


def _journeys_json(journey, projects) -> list[dict]:
    """Every journey with enough to draw its box: paths, and steps done."""
    out = []
    for j in journey.all():
        project = projects.get(j["project_id"])
        shared, others = journey.tracks(j["project_id"])
        tracks = [_track_json(r, journey.nodes.for_roadmap(r.id))
                  for r in ([shared] if shared else []) + others]
        steps = [n for r in ([shared] if shared else []) + others
                 for n in journey.nodes.for_roadmap(r.id) if n.status != "rejected"]
        out.append({"project_id": j["project_id"], "name": project.name if project else "Journey",
                    "kind": j.get("kind", "career"), "purpose": j.get("purpose", ""),
                    "folder": j.get("folder", ""), "layout": layout_of(j),
                    "start_year": j.get("start_year"),
                    "paths": [r.name or r.goal for r in others],
                    "steps": len(steps), "done": sum(n.status == "done" for n in steps),
                    "next": [n["title"] for n in
                             _next(tracks, layout_of(j), term_of(date.today()))[:NEXT_PER_BOX]]})
    return out


def handle_get(journey, projects, today: date | None = None) -> dict:
    settings = journey.settings()
    if settings is None:
        return {"setup": False, "start_year": _guess_start_year(today), "journeys": [],
                "candidates": _candidates(projects, journey.roadmaps, journey.nodes)}
    pid, start = settings["project_id"], settings["start_year"]
    now = term_of(today or date.today())
    shared, others = journey.tracks(pid)
    progress = journey.tasks.progress()
    tracks = [_track_json(r, journey.nodes.for_roadmap(r.id), progress)
              for r in ([shared] if shared else []) + others]
    names = {t["id"]: t["name"] for t in tracks}
    project = projects.get(pid)
    return {
        "setup": True, "project_id": pid, "name": project.name if project else "Journey",
        "kind": settings.get("kind", "career"), "purpose": settings.get("purpose", ""),
        "layout": layout_of(settings),
        "journeys": _journeys_json(journey, projects), "folders": journey.folders(),
        "candidates": _candidates(projects, journey.roadmaps, journey.nodes),
        "start_year": start, "current_term": now, "current_label": term_label(now),
        "current_year": year_of(now, start), "years": _grid(start, now), "tracks": tracks,
        "reflections": journey.reflections(pid),
        "reviews": {str(k): v for k, v in journey.latest_reviews(pid).items()},
        "suggestions": [_suggestion_json(s, names) for s in journey.pending(pid)],
        "next_up": _next(tracks, layout_of(settings), now),
    }


def _guess_start_year(today: date | None) -> int:
    today = today or date.today()
    return today.year - 1 if today.month < 9 else today.year


def _settings(journey, project_id: str = "") -> dict:
    """The open journey, or a named one (the daily scan works on each)."""
    if project_id:
        settings = next((j for j in journey.all() if j["project_id"] == project_id), None)
    else:
        settings = journey.settings()
    if settings is None:
        raise ValueError("set up the journey first")
    return settings


def _own_track(journey, track_id: str):
    """A track in any of your journeys: the assistant on the Journeys page,
    and Today, work on journeys other than the open one."""
    track = journey.roadmaps.get(track_id)
    if track is None or track.project_id not in {j["project_id"] for j in journey.all()}:
        raise ValueError("no such track")
    return track


def _own_step(journey, node_id: str):
    node = journey.nodes.get(node_id)
    if node is None:
        raise ValueError("that step no longer exists")
    _own_track(journey, node.roadmap_id)
    return node


# --- setup and tracks ---------------------------------------------------------


def handle_setup(journey, projects, body: dict) -> dict:
    def run():
        ids = body.get("copy_roadmap_ids") or []
        if not isinstance(ids, list):
            raise ValueError("copy_roadmap_ids must be a list")
        journey.setup(projects, int(body.get("start_year") or _guess_start_year(None)),
                      [str(i) for i in ids], name=str(body.get("name") or ""),
                      purpose=str(body.get("purpose") or ""), kind=str(body.get("kind") or "career"))
        return handle_get(journey, projects)
    return _try(run)


def handle_select(journey, projects, body: dict) -> dict:
    def run():
        journey.select(str(body.get("project_id") or ""))
        return handle_get(journey, projects)
    return _try(run)


def handle_update(journey, projects, body: dict) -> dict:
    """Rename the open journey or change what it's for."""
    def run():
        pid = _settings(journey)["project_id"]
        name = body.get("name")
        purpose = body.get("purpose")
        journey.update(projects, pid, name=None if name is None else str(name),
                       purpose=None if purpose is None else str(purpose))
        return handle_get(journey, projects)
    return _try(run)


def handle_create_track(journey, body: dict) -> dict:
    def run():
        pid = _settings(journey, str(body.get("journey_id") or ""))["project_id"]
        name = str(body.get("name", "")).strip()
        if not name:
            raise ValueError("a track needs a name")
        r = journey.roadmaps.create(str(body.get("goal", "")).strip() or name, pid, name=name)
        return {"track_id": r.id}
    return _try(run)


def handle_update_track(journey, track_id: str, body: dict) -> dict:
    def run():
        _own_track(journey, track_id)
        journey.roadmaps.rename(track_id, name=body.get("name"), goal=body.get("goal"))
        return {"ok": True}
    return _try(run)


def handle_duplicate_track(journey, track_id: str, body: dict) -> dict:
    def run():
        source = _own_track(journey, track_id)
        name = str(body.get("name", "")).strip() or f"{source.name or source.goal} (copy)"
        return {"track_id": duplicate_roadmap(journey.roadmaps, journey.nodes, track_id, name).id}
    return _try(run)


def handle_delete_track(journey, track_id: str) -> dict:
    def run():
        if _own_track(journey, track_id).kind == SHARED_KIND:
            raise ValueError("the shared track can't be deleted")
        journey.roadmaps.delete(track_id)
        return {"ok": True}
    return _try(run)


def handle_add_step(journey, body: dict) -> dict:
    def run():
        track = _own_track(journey, str(body.get("track_id", "")))
        title = str(body.get("title", "")).strip()
        if not title:
            raise ValueError("a step needs a title")
        status = str(body.get("status") or "accepted")
        last = max((n.position for n in journey.nodes.for_roadmap(track.id)), default=-1)
        node = journey.nodes.add(track.id, title[:120], str(body.get("detail", ""))[:1000],
                                 status=status, term=str(body.get("term", "")),
                                 due_date=clean_due(body.get("due", "")))
        # Always at the end of its path, which is where a path map shows it.
        journey.nodes.set_position(node.id, last + 1)
        return {"step": _step_json(journey.nodes.get(node.id), track.id)}
    return _try(run)


def handle_move_step(journey, node_id: str, body: dict) -> dict:
    """Change a step's term and, optionally, its track. `order`, if given,
    is the term's step ids top to bottom after the drop."""
    def run():
        node = _own_step(journey, node_id)
        home = _own_track(journey, node.roadmap_id).project_id
        order = [str(i) for i in body.get("order") or []]
        target = str(body.get("track_id") or node.roadmap_id)
        steps_elsewhere = any(_own_track(journey, _own_step(journey, nid).roadmap_id).project_id != home
                              for nid in order)
        if steps_elsewhere or _own_track(journey, target).project_id != home:
            raise ValueError("a step can only move within its own journey")
        journey.nodes.set_term(node_id, str(body.get("term", "")))
        for index, nid in enumerate(order):
            journey.nodes.set_position(nid, index)
        if target != node.roadmap_id:
            _move_to_track(journey, node_id, target)
        return {"ok": True}
    return _try(run)


def _move_to_track(journey, node_id: str, track_id: str) -> None:
    from mindtrail.organize.db import connect

    # A step's links point at steps in its own track; moving tracks drops them.
    with connect(journey.nodes._path) as conn:
        conn.execute("UPDATE roadmap_nodes SET roadmap_id = ?, depends_on = '' WHERE id = ?",
                     (track_id, node_id))


# --- reflections and reviews --------------------------------------------------


def handle_set_reflection(journey, body: dict) -> dict:
    def run():
        journey.set_reflection(_settings(journey)["project_id"], str(body.get("term", "")),
                               str(body.get("text", "")))
        return {"ok": True}
    return _try(run)


def _step_goals(habits, node_id: str, today: date) -> list[dict]:
    if habits is None:
        return []
    logs = habits.logs_since(today - timedelta(days=STREAK_LOOKBACK_DAYS))
    return [habit_json(h, logs.get(h.id, set()), today) for h in habits.for_node(node_id)]


def _context(journey, profile, today: date | None = None, project_id: str = "", step_id: str = "",
             habits=None, alone: bool = False):
    """What the assistant sees of one journey. alone leaves out the
    profile and the other journeys, for one section of the home context."""
    settings = _settings(journey, project_id)
    pid = settings["project_id"]
    focus = None
    if step_id:
        step = _own_step(journey, step_id)
        focus = (step, journey.tasks.for_node(step.id), _step_goals(habits, step.id, today or date.today()))
    shared, others = journey.tracks(pid)
    steps = {r.id: journey.nodes.for_roadmap(r.id) for r in ([shared] if shared else []) + others}
    node_ids = [n.id for ns in steps.values() for n in ns]
    names = journey.names()
    siblings = [{"name": names.get(j["project_id"], "Journey"), "folder": j.get("folder", "")}
                for j in journey.all() if j["project_id"] != pid]
    return journey_ai.build_context(settings["start_year"], term_of(today or date.today()),
                                    shared, others, steps,
                                    "" if alone or not profile else profile.get().content,
                                    purpose=settings.get("purpose", ""),
                                    kind=settings.get("kind", "career"),
                                    folder=settings.get("folder", ""), others=() if alone else siblings,
                                    today=(today or date.today()).isoformat(), focus=focus,
                                    progress=journey.tasks.progress(),
                                    tasks_by_node={i: journey.tasks.for_node(i) for i in node_ids},
                                    goals_by_node={i: habits.for_node(i) for i in node_ids} if habits else {},
                                    goals_by_track={tid: habits.for_track(tid) for tid in steps} if habits else {},
                                    journey_goals=habits.for_journey(pid) if habits else [],
                                    journey_id=pid, name=names.get(pid, "Journey"),
                                    layout=layout_of(settings),
                                    reflections=journey.reflections(pid))


def _home_context(journey, profile, habits=None, today: date | None = None):
    """Every journey at once, for the assistant on the Journeys page."""
    sections = [_context(journey, profile, today, j["project_id"], habits=habits, alone=True)
                for j in journey.all()]
    return journey_ai.build_home_context(sections, profile.get().content if profile else "",
                                         (today or date.today()).isoformat())


def handle_review(journey, projects, llm, profile, body: dict, today: date | None = None) -> dict:
    """Review one past year, save it, and queue its steps as suggestions."""
    def run():
        settings = _settings(journey)
        pid, start = settings["project_id"], settings["start_year"]
        now = term_of(today or date.today())
        year = int(body.get("year") or 1)
        if not 1 <= year <= min(year_of(now, start), YEARS):
            raise ValueError("you can only review a year that has started")
        ctx = _context(journey, profile, today)
        terms = year_terms(start, year)
        review = journey_ai.review_year(llm, ctx, year, terms, journey.reflections(pid), now)
        shared, _ = journey.tracks(pid)
        for step in review["done_steps"]:
            journey.add_suggestion(pid, "review", "add_done", step["title"], step["detail"],
                                   step["term"], shared.id if shared else "",
                                   reason=f"From your Year {year} notes")
        for step in review["next_steps"]:
            journey.add_suggestion(pid, "review", "add_step", step["title"], step["detail"],
                                   step["term"], step["track_id"] or (shared.id if shared else ""),
                                   reason=f"Year {year} review")
        journey.add_review(pid, year, review)
        return handle_get(journey, projects, today)
    return _try(run)


# --- chat ---------------------------------------------------------------------


HOME = "home"   # the scope of the assistant on the Journeys page


def _scope_id(journey, scope: str) -> str:
    """Whose chats: the open journey's, or the Journeys page's."""
    return HOME if scope == HOME else _settings(journey)["project_id"]


def handle_delete_review(journey, body: dict) -> dict:
    def run():
        journey.delete_reviews(_settings(journey)["project_id"], int(body.get("year")))
        return {"ok": True}
    return _try(run)


def _own_chat(journey, chats, chat_id: str, scope: str = "") -> dict:
    """A chat that belongs to the open journey (or to the Journeys page)."""
    chat = chats.get(chat_id)
    if chat is None or chat["project_id"] != _scope_id(journey, scope):
        raise ValueError("no such chat")
    return chat


def handle_chats(journey, chats, scope: str = "") -> dict:
    return _try(lambda: {"chats": chats.list(_scope_id(journey, scope))})


def handle_get_chat(journey, chats, chat_id: str, scope: str = "") -> dict:
    return _try(lambda: {"chat": _own_chat(journey, chats, chat_id, scope)})


def handle_delete_chat(journey, chats, chat_id: str, scope: str = "") -> dict:
    def run():
        _own_chat(journey, chats, chat_id, scope)
        chats.delete(chat_id)
        return {"ok": True}
    return _try(run)


def _asked(ask: dict | None) -> str:
    if not ask:
        return ""
    return f"\n[You asked: {ask['question']}" + (f" Choices: {' / '.join(ask['choices'])}" if ask["choices"] else "") + "]"


MAX_HINT_CHARS = 300


def handle_chat(journey, chats, llm, profile, body: dict, habits=None, store=None) -> dict:
    """One turn with the journey assistant, saved to a chat. With no
    chat_id a new chat is started; the history always comes from the
    saved chat, never the client. Files sent with it (body attachments:
    [{name, text}]) are read by the model; the saved documents and notes
    that match the message (store) are added for it to draw on."""
    def run():
        typed = str(body.get("message", "")).strip()
        message, saved_message = with_attachments(typed, body.get("attachments"))
        hint = " ".join(str(body.get("hint", "")).split())[:MAX_HINT_CHARS]
        if hint and message:   # guidance from a button (e.g. ask first), read but not saved
            message = f"{message} {hint}"
        if not message:
            raise ValueError("message was empty")
        scope = str(body.get("scope", ""))
        chat_id = str(body.get("chat_id", ""))
        chat = _own_chat(journey, chats, chat_id, scope) if chat_id else chats.create(_scope_id(journey, scope))
        # The model sees the questions it asked, so an answer like "20-25 in" makes sense to it.
        history = [{"role": m["role"], "content": m["content"] + _asked(m.get("ask"))} for m in chat["messages"]]
        ctx = _home_context(journey, profile, habits) if scope == HOME else \
            _context(journey, profile, step_id=str(body.get("step_id", "")), habits=habits)
        step = journey.nodes.get(str(body.get("step_id", ""))) if body.get("step_id") else None
        notes = document_notes(store, " ".join(filter(None, [typed, step.title if step else ""])))
        reply, actions, ask = journey_ai.journey_chat(llm, ctx, history, message, auto=bool(body.get("auto")),
                                                      notes=notes)
        saved = chats.append_turn(chat["id"], saved_message, reply, [asdict(a) for a in actions],
                                  title=str(body.get("title", "")), ask=ask)
        return {"chat": saved}
    return _try(run)


EDITABLE_FIELDS = ("title", "detail", "note", "name", "purpose", "goal", "due", "fact", "folder")


def handle_chat_action(journey, chats, profile, chat_id: str, body: dict, habits=None) -> dict:
    """Resolve a proposal (accepted/rejected) or save an edit to it. An
    edit is re-checked and re-labelled the same way the model's own
    proposals are."""
    def run():
        scope = str(body.get("scope", ""))
        chat = _own_chat(journey, chats, chat_id, scope)
        mi, ai = int(body.get("message", -1)), int(body.get("action", -1))
        raw = body.get("fields") or {}
        fields = {k: str(v) for k, v in raw.items() if k in EDITABLE_FIELDS}
        if isinstance(raw.get("sub_steps"), list):   # the ticked part of a plan
            fields["sub_steps"] = raw["sub_steps"]
        if fields:
            try:
                current = chat["messages"][mi]["actions"][ai]
            except (IndexError, KeyError, TypeError):
                raise ValueError("no such proposal") from None
            ctx = _home_context(journey, profile, habits) if scope == HOME else \
                _context(journey, profile, habits=habits)
            revised = journey_ai.revise_action({**current, **fields}, ctx)
            if revised is None:
                raise ValueError("that edit doesn't make a valid change")
            fields = asdict(revised)
        return {"chat": chats.update_action(chat_id, mi, ai, str(body.get("resolved", "")), fields)}
    return _try(run)


def handle_apply(journey, body: dict, projects=None, habits=None, profile=None) -> dict:
    """Apply one chat action the user accepted. Returns which track and
    steps changed, so the Timeline can light them up."""
    def run():
        a = body.get("action") or {}
        kind = a.get("type")
        if kind in ("create_journey", "set_folder", "edit_journey", "delete_journey", "set_layout"):
            return _apply_journey_action(journey, projects, a)
        if kind == "set_term_note":
            pid = _settings(journey, str(a.get("journey_id") or ""))["project_id"]
            journey.set_reflection(pid, str(a.get("term", "")), str(a.get("note", "")))
            return {"track_id": "", "changed": []}
        if kind in ("edit_sub_step", "delete_sub_step", "edit_daily_goal", "delete_daily_goal",
                    "log_daily_goal"):
            return _apply_inside_step(journey, habits, a)
        if kind in ("remember", "edit_fact", "forget"):
            return _apply_fact(profile, a)
        node_id, track_id = str(a.get("node_id", "")), str(a.get("track_id", ""))
        if kind == "add_step":
            res = handle_add_step(journey, {"track_id": track_id, "title": a.get("title"),
                                            "detail": a.get("detail", ""), "term": a.get("term", ""),
                                            "due": a.get("due", "")})
            if "error" in res:
                raise ValueError(res["error"])
            return {"track_id": track_id, "changed": [res["step"]["id"]]}
        if kind == "plan_step":
            node = _own_step(journey, node_id)
            subs = [sub for sub in a.get("sub_steps") or [] if str(sub.get("title", "")).strip()]
            if not subs:
                raise ValueError("pick at least one sub-step")
            if a.get("mode") == "replace":
                journey.tasks.clear_unfinished(node_id)
            for sub in subs:
                journey.tasks.add(node_id, sub["title"], sub.get("detail", ""), sub.get("due", ""),
                                  sub.get("needs", ""), sub.get("unit", ""))
            journey.tasks.sort_by_date(node_id)
            return {"track_id": node.roadmap_id, "changed": [node_id]}
        if kind == "add_daily_goal":
            if habits is None:
                raise ValueError("can't add daily goals here")
            target = _goal_target(journey, a)
            habits.create(str(a.get("name", "")), int(a.get("per_week") or 7), **target)
            return {"track_id": track_id, "changed": [node_id] if node_id else []}
        if kind in ("set_status", "move_term", "set_note", "delete_step", "edit_step"):
            node = _own_step(journey, node_id)
            if kind == "set_status":
                journey.nodes.set_status(node_id, str(a.get("status", "")))
            elif kind == "edit_step":
                journey.nodes.rename(node_id, str(a.get("title") or node.title)[:120],
                                     str(a.get("detail") or node.detail)[:1000])
                if a.get("due"):
                    journey.nodes.set_due_date(node_id, str(a["due"]))
            elif kind == "move_term":
                if a.get("term"):
                    journey.nodes.set_term(node_id, str(a["term"]))
                if a.get("track_id") and a["track_id"] != node.roadmap_id:
                    if _own_track(journey, a["track_id"]).project_id != \
                            _own_track(journey, node.roadmap_id).project_id:
                        raise ValueError("a step can only move to a track in its own journey")
                    _move_to_track(journey, node_id, a["track_id"])
                    return {"track_id": a["track_id"], "changed": [node_id]}
            elif kind == "set_note":
                journey.nodes.set_note(node_id, str(a.get("note", "")))
            else:
                journey.nodes.delete(node_id)
                return {"track_id": node.roadmap_id, "changed": []}
            return {"track_id": node.roadmap_id, "changed": [node_id]}
        if kind == "create_track":
            res = handle_create_track(journey, {"name": a.get("name"), "goal": a.get("goal"),
                                                "journey_id": a.get("journey_id", "")})
            if "error" not in res:
                steps = [journey.nodes.add(res["track_id"], st["title"], st.get("detail", ""),
                                           status="accepted", term=st.get("term", ""))
                         for st in a.get("steps") or [] if str(st.get("title", "")).strip()]
                return {"track_id": res["track_id"], "changed": [n.id for n in steps]}
        elif kind == "duplicate_track":
            res = handle_duplicate_track(journey, track_id, {"name": a.get("name")})
        elif kind in ("rename_track", "edit_track"):
            res = handle_update_track(journey, track_id, {"name": a.get("name") or None,
                                                          "goal": a.get("goal") or None})
            res = {**res, "track_id": track_id}
        elif kind == "delete_track":
            res = {**handle_delete_track(journey, track_id), "track_id": ""}
        else:
            raise ValueError("unknown action")
        if "error" in res:
            raise ValueError(res["error"])
        return {"track_id": res["track_id"], "changed": []}
    return _try(run)


def _apply_fact(profile, a: dict) -> dict:
    """Add, change or remove one line of the profile."""
    if profile is None:
        raise ValueError("can't change what it knows about you here")
    lines = profile.get().content.split("\n")
    fact, old = " ".join(str(a.get("fact", "")).split()), str(a.get("old_fact", ""))
    at = next((i for i, line in enumerate(lines) if " ".join(line.split()) == old), -1) if old else -1
    if a.get("type") == "remember":
        lines = [*"\n".join(lines).rstrip().split("\n"), fact] if any(x.strip() for x in lines) else [fact]
    elif at < 0:
        raise ValueError("that fact has changed since; ask again")
    elif a.get("type") == "edit_fact":
        lines = [fact if i == at else x for i, x in enumerate(lines)]
    else:
        lines = [x for i, x in enumerate(lines) if i != at]
    text = "\n".join(lines).strip()
    if len(text) > MAX_PROFILE_CHARS:
        raise ValueError("what it knows about you is full; forget something first")
    profile.save(text)
    return {"track_id": "", "changed": [], "facts": True}


def _apply_inside_step(journey, habits, a: dict) -> dict:
    """Edits to one sub-step or daily goal, from the assistant."""
    kind = a.get("type")
    if kind in ("edit_sub_step", "delete_sub_step"):
        task = journey.tasks.get(str(a.get("task_id", "")))
        if task is None:
            raise ValueError("that sub-step no longer exists")
        node = _own_step(journey, task.node_id)
        if kind == "delete_sub_step":
            journey.tasks.delete(task.id)
        else:
            done = {"yes": True, "no": False}.get(a.get("done"))
            journey.tasks.update(task.id, title=a.get("title") or None, detail=a.get("detail") or None,
                                 due=a.get("due") or None, done=done, needs=a.get("needs") or None,
                                 unit=a.get("unit") or None, result=a.get("result") or None)
            if done is not None:
                journey.sync_step_done(node.id)
        return {"track_id": node.roadmap_id, "changed": [node.id]}
    goal = habits.get(str(a.get("goal_id", ""))) if habits else None
    if goal is None or goal.id not in habits.steps():
        raise ValueError("that daily goal no longer exists")
    _own_goal(journey, goal)
    if kind == "log_daily_goal":
        today = date.today()
        if today not in habits.logs_since(today).get(goal.id, set()):
            habits.toggle(goal.id, today, today)
    elif kind == "delete_daily_goal":
        habits.delete(goal.id)
    else:
        fields = {k: v for k, v in (("name", a.get("name")), ("target_per_week", a.get("per_week"))) if v}
        if fields:
            habits.update(goal.id, fields)
        if any(a.get(k) for k in ("node_id", "track_id", "journey_id")):
            [(column, value)] = _goal_target(journey, a).items()
            habits.set_scope(goal.id, column, value)
    return {"track_id": "", "changed": [goal.node_id] if goal.node_id else []}


def _goal_target(journey, a: dict) -> dict:
    """Where a daily goal from the assistant goes: a step, a path, or a
    journey (named, or the open one)."""
    if a.get("node_id"):
        return {"node_id": _own_step(journey, str(a["node_id"])).id}
    if a.get("track_id"):
        return {"track_id": _own_track(journey, str(a["track_id"])).id}
    return {"journey_id": _settings(journey, str(a.get("journey_id") or ""))["project_id"]}


def _own_goal(journey, goal) -> None:
    """A daily goal that serves something in one of your journeys."""
    if goal.node_id:
        _own_step(journey, goal.node_id)
    elif goal.track_id:
        _own_track(journey, goal.track_id)
    else:
        _settings(journey, goal.journey_id)


def _apply_journey_action(journey, projects, a: dict) -> dict:
    """New journeys, folders, renames and deletes. A new journey is made
    beside this one and this one stays open, so accepting doesn't yank
    you somewhere else. journey_id names the journey; '' is the open one."""
    settings = _settings(journey, "" if a.get("type") == "create_journey" else str(a.get("journey_id") or ""))
    pid = settings["project_id"]
    if a.get("type") == "set_folder":
        journey.set_folder(pid, str(a.get("folder", "")))
        return {"track_id": "", "changed": []}
    if a.get("type") == "set_layout":
        journey.set_layout(pid, str(a.get("layout", "")))
        return {"track_id": "", "changed": []}
    if projects is None:
        raise ValueError("can't change journeys here")
    if a.get("type") == "edit_journey":
        journey.update(projects, pid, name=a.get("name") or None, purpose=a.get("purpose") or None)
        return {"track_id": "", "changed": []}
    if a.get("type") == "delete_journey":
        projects.delete(pid)
        return {"track_id": "", "changed": [], "deleted_journey": pid}
    made = journey.setup(projects, settings["start_year"], name=str(a.get("name", "")),
                         purpose=str(a.get("purpose", "")), kind="general")
    if str(a.get("folder", "")).strip():
        journey.set_folder(made["project_id"], str(a["folder"]))
    journey.select(pid)
    return {"track_id": "", "changed": [], "journey_id": made["project_id"]}


def handle_set_layout(journey, body: dict) -> dict:
    return _try(lambda: {"journey": journey.set_layout(str(body.get("project_id", "")),
                                                       str(body.get("layout", "")))})


def handle_set_folder(journey, body: dict) -> dict:
    return _try(lambda: {"journey": journey.set_folder(str(body.get("project_id", "")),
                                                       str(body.get("folder", "")))})


def handle_rename_folder(journey, body: dict) -> dict:
    def run():
        journey.rename_folder(str(body.get("old", "")), str(body.get("new", "")))
        return {"folders": journey.folders()}
    return _try(run)


# --- suggestions --------------------------------------------------------------


def handle_accept(journey, suggestion_id: str, body: dict) -> dict:
    def run():
        node_id = journey.accept_suggestion(suggestion_id, str(body.get("roadmap_id", "")))
        node = journey.nodes.get(node_id)
        return {"node_id": node_id, "track_id": node.roadmap_id if node else ""}
    return _try(run)


def handle_dismiss(journey, suggestion_id: str) -> dict:
    return _try(lambda: journey.dismiss_suggestion(suggestion_id) or {"ok": True})


def _queue(journey, profile, llm, source: str, items: list[str], project_id: str = "") -> dict:
    pid = _settings(journey, project_id)["project_id"]
    if not items:
        return {"added": 0, "looked_at": 0}
    found = journey_ai.find_evidence(llm, _context(journey, profile, project_id=pid), source, items)
    added = 0
    for s in found:
        if journey.add_suggestion(pid, source, s["kind"], s["title"], s["detail"], s["term"],
                                  s["track_id"], s["node_id"], s["reason"]):
            added += 1
    return {"added": added, "looked_at": len(items)}


def mindtrail_items(jobs, practice, rounds, chats, github_cache: dict,
                    today: date | None = None) -> list[str]:
    """Dated one-liners from what's already in Mind Trail, newest first."""
    since = ((today or date.today()) - timedelta(days=EVIDENCE_DAYS)).isoformat()
    items: list[tuple[str, str]] = []
    for p in practice.all():
        if p.solved_on >= since:
            items.append((p.solved_on, f"solved practice problem {p.title} "
                                       f"({p.difficulty}{', ' + p.topic if p.topic else ''})"))
    for a in jobs.all():
        when = a.applied_at or a.created_at[:10]
        if when >= since:
            items.append((when, f"job application: {a.company} {a.role}, stage {a.stage}"))
        for r in rounds.for_application(a.id):
            if r.date and r.date >= since:
                items.append((r.date, f"{r.kind} interview at {a.company}"))
    for c in chats.all():
        if c.created_at[:10] >= since and c.title:
            items.append((c.created_at[:10], f"asked Mind Trail about: {c.title}"))
    for g in (github_cache or {}).get("items", []):
        items.append(((g.get("updated_at") or "")[:10], f"GitHub: {g.get('title')} ({g.get('repo')})"))
    items.sort(reverse=True)
    return [f"{d}: {text}" for d, text in items[:MAX_EVIDENCE_ITEMS]]


def handle_scan_mindtrail(journey, profile, llm, deps_like) -> dict:
    def run():
        _settings(journey)
        d = deps_like
        items = mindtrail_items(d.jobs, d.practice, d.rounds, d.chats, d.github.cached())
        return _queue(journey, profile, llm, "mindtrail", items)
    return _try(run)


def handle_scan_gmail(journey, profile, llm, gmail, project_id: str = "") -> dict:
    def run():
        _settings(journey, project_id)
        since = (date.today() - timedelta(days=GMAIL_DAYS)).strftime("%Y/%m/%d")
        try:
            ids = gmail.search_ids(f"{GMAIL_QUERY} after:{since}", limit=GMAIL_LIMIT)
            messages = [gmail.get(i) for i in ids]
        except GoogleAuthError as exc:
            return {"error": f"Gmail isn't connected: {exc}"}
        except GoogleFetchError as exc:
            return {"error": f"couldn't reach Gmail: {exc}"}
        items = [f"{m.received_at[:10]}: email from {m.sender}: {m.subject} - {m.body[:300]}"
                 for m in messages]
        return _queue(journey, profile, llm, "gmail", items, project_id)
    return _try(run)


def handle_scan_calendar(journey, profile, llm, events: CalendarEvents, today: date | None = None,
                         project_id: str = "") -> dict:
    """Upcoming events become suggested steps; nothing is marked done."""
    def run():
        _settings(journey, project_id)
        start = today or date.today()
        try:
            found = events.between(start, start + timedelta(days=CALENDAR_DAYS))
        except GoogleAuthError as exc:
            return {"error": f"Calendar isn't connected: {exc}"}
        except GoogleFetchError as exc:
            return {"error": f"couldn't reach Calendar: {exc}"}
        items = [f"{e.date}: {e.title}" + (" (all day)" if e.all_day else "") for e in found]
        return _queue(journey, profile, llm, "calendar", items, project_id)
    return _try(run)


CANVAS_DAYS = 30


def canvas_to_school(journey, canvas, project_id: str, today: date | None = None) -> dict:
    """Upcoming Canvas assignments become suggested steps on a journey's
    School path, in the term they're due. No model call - a deadline is
    a fact; the suggestion is there so you choose what goes on the plan."""
    school = journey.school_track(project_id)
    if school is None:
        return {"added": 0}
    added = 0
    for e in canvas.upcoming(today or date.today(), CANVAS_DAYS):
        due = date.fromisoformat(e["due"])
        if journey.add_suggestion(project_id, "canvas", "add_step", e["title"], e.get("url", ""),
                                  term_of(due), school.id, reason=f"Due {due:%b} {due.day}"):
            added += 1
    return {"added": added}


def handle_step_to_calendar(journey, node_id: str, body: dict, create=create_event) -> dict:
    """Put one step on Google Calendar as a time block."""
    def run():
        node = _own_step(journey, node_id)
        try:
            start = datetime.fromisoformat(f"{body.get('date', '')}T{body.get('time', '')}").astimezone()
        except ValueError:
            raise ValueError("pick a day and a start time") from None
        try:
            link = create(node.title, node.detail or "", start,
                                            int(body.get("minutes") or 60))
        except GoogleAuthError as exc:
            return {"error": str(exc)}
        except GoogleFetchError as exc:
            return {"error": f"couldn't reach Calendar: {exc}"}
        return {"ok": True, "link": link}
    return _try(run)


def handle_import_gemini(journey, profile, llm, state, body: dict) -> dict:
    """Prompts newer than the last import, newest kept if there are too many."""
    def run():
        _settings(journey)
        prompts = parse_takeout(str(body.get("text", "")))
        through = state.get(GEMINI_STATE_KEY, "") or ""
        fresh = [p for p in prompts if p.date > through]
        if not prompts:
            raise ValueError("no Gemini prompts found in that file")
        picked = fresh[-MAX_GEMINI_PROMPTS:]
        result = _queue(journey, profile, llm, "gemini", [f"{p.date}: {p.text}" for p in picked])
        if fresh:
            state.set(GEMINI_STATE_KEY, fresh[-1].date)
        return {**result, "found": len(prompts), "new": len(fresh)}
    return _try(run)


def handle_paste(journey, profile, llm, body: dict) -> dict:
    def run():
        text = str(body.get("text", "")).strip()[:MAX_PASTE]
        if not text:
            raise ValueError("paste a chat first")
        return _queue(journey, profile, llm, "paste", [f"{date.today().isoformat()}: {text}"])
    return _try(run)


def _today_work(journey, habits, pid: str, today: date) -> dict:
    """This journey's sub-steps due by today and its daily goals."""
    due = [t for t in journey.tasks.due_by(today.isoformat()) if t["project_id"] == pid]
    goals = {hid: s for hid, s in (habits.steps() if habits else {}).items() if s["project_id"] == pid}
    logged = habits.logs_since(today) if habits else {}
    done = sum(1 for hid in goals if today in logged.get(hid, set()))
    first = due[0]["node_id"] if due else next((s["id"] for s in goals.values() if s["id"]), "")
    return {"due": len(due), "goals_done": done, "goals_total": len(goals), "step_id": first}


def handle_today(journey, projects, today: date | None = None, habits=None) -> dict:
    """The Today widget: this term's progress, what to do today, and the
    first thing next."""
    data = handle_get(journey, projects, today)
    if not data["setup"]:
        return {"setup": False}
    now, is_map = data["current_term"], data["layout"] == "map"
    # A path map has no terms, so its tile counts the whole map.
    in_term = [s for t in data["tracks"] for s in t["steps"]
               if (is_map or s["term"] == now) and s["status"] != "rejected"]
    return {"setup": True, "name": data["name"], "project_id": data["project_id"],
            "label": "All paths" if is_map else data["current_label"], "year": data["current_year"],
            "map": is_map,
            "done": sum(1 for s in in_term if s["status"] == "done"), "total": len(in_term),
            "next": data["next_up"][:1], "pending": len(data["suggestions"]),
            "today": _today_work(journey, habits, data["project_id"], today or date.today())}


CAPTURE_MAX = 2000


def handle_capture(journey, body: dict) -> dict:
    """A note or link sent from your phone, queued as a suggestion on the
    journey you picked. The first line is the step; the rest its detail."""
    def run():
        text = str(body.get("text", "")).strip()[:CAPTURE_MAX]
        if not text:
            raise ValueError("write something first")
        pid = _settings(journey, str(body.get("project_id", "")))["project_id"]
        title, _, rest = text.partition("\n")
        s = journey.add_suggestion(pid, "phone", "add_step", title.strip(), rest.strip(),
                                   reason="Sent from your phone")
        return {"ok": True, "duplicate": s is None}
    return _try(run)
