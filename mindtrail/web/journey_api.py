"""Handlers for the 4-year journey (organize/journey.py).

`handle_get` returns the whole journey in one response - tracks, steps,
the year/term grid, reflections, reviews, pending suggestions and what's
next - so the Timeline re-renders from a single fetch after any change.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from mindtrail.advice import journey_ai
from mindtrail.integrations.gemini_takeout import parse_takeout
from mindtrail.integrations.google_api import GoogleAuthError, GoogleFetchError
from mindtrail.llm import LLMError
from mindtrail.organize.journey import YEARS
from mindtrail.organize.roadmaps import SHARED_KIND, duplicate_roadmap
from mindtrail.organize.terms import (
    next_term, term_label, term_of, term_rank, year_of, year_terms,
)

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
GEMINI_STATE_KEY = "journey_gemini_through"


def _try(fn):
    try:
        return fn()
    except (ValueError, LLMError) as exc:
        return {"error": str(exc)}


def _step_json(n, track_id: str) -> dict:
    return {"id": n.id, "track_id": track_id, "title": n.title, "detail": n.detail,
            "status": n.status, "note": n.note, "term": n.term, "due_date": n.due_date}


def _track_json(r, steps: list) -> dict:
    ordered = sorted(steps, key=lambda n: (STATUS_ORDER.get(n.status, 1), n.created_at))
    return {"id": r.id, "name": r.name or r.goal, "goal": r.goal, "shared": r.kind == SHARED_KIND,
            "steps": [_step_json(n, r.id) for n in ordered]}


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


def handle_get(journey, projects, today: date | None = None) -> dict:
    settings = journey.settings()
    if settings is None:
        return {"setup": False, "start_year": _guess_start_year(today),
                "candidates": _candidates(projects, journey.roadmaps, journey.nodes)}
    pid, start = settings["project_id"], settings["start_year"]
    now = term_of(today or date.today())
    shared, others = journey.tracks(pid)
    tracks = [_track_json(r, journey.nodes.for_roadmap(r.id))
              for r in ([shared] if shared else []) + others]
    names = {t["id"]: t["name"] for t in tracks}
    project = projects.get(pid)
    return {
        "setup": True, "project_id": pid, "name": project.name if project else "Journey",
        "start_year": start, "current_term": now, "current_label": term_label(now),
        "current_year": year_of(now, start), "years": _grid(start, now), "tracks": tracks,
        "reflections": journey.reflections(pid),
        "reviews": {str(k): v for k, v in journey.latest_reviews(pid).items()},
        "suggestions": [_suggestion_json(s, names) for s in journey.pending(pid)],
        "next_up": next_up(tracks, now),
    }


def _guess_start_year(today: date | None) -> int:
    today = today or date.today()
    return today.year - 1 if today.month < 9 else today.year


def _settings(journey) -> dict:
    settings = journey.settings()
    if settings is None:
        raise ValueError("set up the journey first")
    return settings


def _own_track(journey, track_id: str):
    track = journey.roadmaps.get(track_id)
    if track is None or track.project_id != _settings(journey)["project_id"]:
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
                      [str(i) for i in ids])
        return handle_get(journey, projects)
    return _try(run)


def handle_create_track(journey, body: dict) -> dict:
    def run():
        pid = _settings(journey)["project_id"]
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
        node = journey.nodes.add(track.id, title[:120], str(body.get("detail", ""))[:1000],
                                 status=status, term=str(body.get("term", "")))
        return {"step": _step_json(node, track.id)}
    return _try(run)


def handle_move_step(journey, node_id: str, body: dict) -> dict:
    """Change a step's term and, optionally, its track."""
    def run():
        node = _own_step(journey, node_id)
        journey.nodes.set_term(node_id, str(body.get("term", "")))
        target = str(body.get("track_id") or node.roadmap_id)
        if target != node.roadmap_id:
            _own_track(journey, target)
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


def _context(journey, profile, today: date | None = None):
    settings = _settings(journey)
    shared, others = journey.tracks(settings["project_id"])
    steps = {r.id: journey.nodes.for_roadmap(r.id) for r in ([shared] if shared else []) + others}
    return journey_ai.build_context(settings["start_year"], term_of(today or date.today()),
                                    shared, others, steps, profile.get().content if profile else "")


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


def handle_chat(journey, llm, profile, body: dict) -> dict:
    def run():
        ctx = _context(journey, profile)
        history = body.get("history") if isinstance(body.get("history"), list) else []
        reply, actions = journey_ai.journey_chat(llm, ctx, history, str(body.get("message", "")))
        return {"reply": reply, "actions": [asdict(a) for a in actions]}
    return _try(run)


def handle_apply(journey, body: dict) -> dict:
    """Apply one chat action the user accepted. Returns which track and
    steps changed, so the Timeline can light them up."""
    def run():
        a = body.get("action") or {}
        kind = a.get("type")
        node_id, track_id = str(a.get("node_id", "")), str(a.get("track_id", ""))
        if kind == "add_step":
            res = handle_add_step(journey, {"track_id": track_id, "title": a.get("title"),
                                            "detail": a.get("detail", ""), "term": a.get("term", "")})
            if "error" in res:
                raise ValueError(res["error"])
            return {"track_id": track_id, "changed": [res["step"]["id"]]}
        if kind in ("set_status", "move_term", "set_note", "delete_step"):
            node = _own_step(journey, node_id)
            if kind == "set_status":
                journey.nodes.set_status(node_id, str(a.get("status", "")))
            elif kind == "move_term":
                journey.nodes.set_term(node_id, str(a.get("term", "")))
            elif kind == "set_note":
                journey.nodes.set_note(node_id, str(a.get("note", "")))
            else:
                journey.nodes.delete(node_id)
                return {"track_id": node.roadmap_id, "changed": []}
            return {"track_id": node.roadmap_id, "changed": [node_id]}
        if kind == "create_track":
            res = handle_create_track(journey, {"name": a.get("name"), "goal": a.get("goal")})
            if "error" not in res:
                steps = [journey.nodes.add(res["track_id"], st["title"], st.get("detail", ""),
                                           status="accepted", term=st.get("term", ""))
                         for st in a.get("steps") or [] if str(st.get("title", "")).strip()]
                return {"track_id": res["track_id"], "changed": [n.id for n in steps]}
        elif kind == "duplicate_track":
            res = handle_duplicate_track(journey, track_id, {"name": a.get("name")})
        elif kind == "rename_track":
            res = handle_update_track(journey, track_id, {"name": a.get("name")})
            res = {**res, "track_id": track_id}
        else:
            raise ValueError("unknown action")
        if "error" in res:
            raise ValueError(res["error"])
        return {"track_id": res["track_id"], "changed": []}
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


def _queue(journey, profile, llm, source: str, items: list[str]) -> dict:
    pid = _settings(journey)["project_id"]
    if not items:
        return {"added": 0, "looked_at": 0}
    found = journey_ai.find_evidence(llm, _context(journey, profile), source, items)
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


def handle_scan_gmail(journey, profile, llm, gmail) -> dict:
    def run():
        _settings(journey)
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
        return _queue(journey, profile, llm, "gmail", items)
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


def handle_today(journey, projects, today: date | None = None) -> dict:
    """The Today widget: this term's progress and the first thing next."""
    data = handle_get(journey, projects, today)
    if not data["setup"]:
        return {"setup": False}
    now = data["current_term"]
    in_term = [s for t in data["tracks"] for s in t["steps"]
               if s["term"] == now and s["status"] != "rejected"]
    return {"setup": True, "label": data["current_label"], "year": data["current_year"],
            "done": sum(1 for s in in_term if s["status"] == "done"), "total": len(in_term),
            "next": data["next_up"][:1], "pending": len(data["suggestions"])}
