"""Request handlers for life admin: people, the school calendar, and the
reading list. Same contract as the other *_api modules."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from mindtrail.integrations.canvas import EVENTS_KEY, CanvasFeed
from mindtrail.organize.people import PeopleStore, days_since, is_due


def person_json(p, today: date, companies: dict) -> dict:
    return {**asdict(p), "days_since": days_since(p, today), "due": is_due(p, today),
            "company": companies.get(p.application_id, "")}


def handle_list_people(people: PeopleStore, jobs, today: date | None = None) -> dict:
    today = today or date.today()
    companies = {a.id: a.company for a in jobs.all()}
    return {"people": [person_json(p, today, companies) for p in people.all()],
            "applications": [{"id": a.id, "company": a.company, "role": a.role}
                             for a in jobs.all()]}


def handle_create_person(people: PeopleStore, body: dict) -> dict:
    try:
        person = people.create(str(body.get("name", "")), str(body.get("context", "")),
                               body.get("nudge_every_days", 0), str(body.get("last_contacted", "")))
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}
    return {"person": asdict(person)}


def handle_update_person(people: PeopleStore, person_id: str, body: dict,
                         today: date | None = None) -> dict:
    """{"talked_today": true} is shorthand for last_contacted = today."""
    fields = dict(body)
    if fields.pop("talked_today", False):
        fields["last_contacted"] = (today or date.today()).isoformat()
    try:
        person = people.update(person_id, fields)
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}
    return {"person": asdict(person)}


def handle_delete_person(people: PeopleStore, person_id: str) -> dict:
    try:
        people.delete(person_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


def nudges_today(people: PeopleStore, today: date) -> list[dict]:
    return [{"person_id": p.id, "name": p.name, "context": p.context,
             "days_since": days_since(p, today)} for p in people.due(today)]


# --- Canvas -----------------------------------------------------------------


def canvas_status(canvas: CanvasFeed, state, error: str = "") -> dict:
    """Never echoes the feed link back - only that one is set and where."""
    from urllib.parse import urlparse
    cache = state.get(EVENTS_KEY) or {}
    url = canvas.url()
    status = {"linked": bool(url), "host": urlparse(url).hostname if url else "",
              "fetched_at": cache.get("fetched_at", ""), "count": len(cache.get("events", []))}
    if error:
        status["error"] = error
    return status


def handle_get_canvas(canvas: CanvasFeed, state) -> dict:
    return canvas_status(canvas, state)


def handle_set_canvas(canvas: CanvasFeed, state, body: dict) -> dict:
    try:
        canvas.set_url(str(body.get("url", "")))
    except ValueError as exc:
        return {"error": str(exc)}
    if not canvas.url():
        return canvas_status(canvas, state)
    result = canvas.refresh()
    return canvas_status(canvas, state, result.get("error", ""))


def handle_refresh_canvas(canvas: CanvasFeed, state) -> dict:
    result = canvas.refresh()
    return canvas_status(canvas, state, result.get("error", ""))


def handle_canvas_done(canvas: CanvasFeed, body: dict) -> dict:
    uid = str(body.get("uid", ""))
    if not uid:
        return {"error": "uid required"}
    canvas.mark_done(uid, bool(body.get("done", True)))
    return {"ok": True}
