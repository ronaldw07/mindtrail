"""Handlers for the recruiting tools: interview rounds, the story bank,
the practice log, and offers."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date


def _try(fn):
    try:
        return fn()
    except ValueError as exc:
        return {"error": str(exc)}


# --- interview rounds ---------------------------------------------------------


def handle_add_round(rounds, application_id: str, body: dict) -> dict:
    def run():
        r = rounds.add(application_id, str(body.get("date", "")), str(body.get("kind", "other")),
                       str(body.get("interviewer", "")), str(body.get("person_id", "")),
                       str(body.get("prep_notes", "")), str(body.get("questions", "")))
        return {"round": asdict(r)}
    return _try(run)


def handle_update_round(rounds, round_id: str, body: dict) -> dict:
    return _try(lambda: {"round": asdict(rounds.update(round_id, body))})


def handle_delete_round(rounds, round_id: str) -> dict:
    return _try(lambda: rounds.delete(round_id) or {"ok": True})


def handle_recruiting_today(rounds, practice, today: date | None = None) -> dict:
    """What Today reminds you about: interviews in the next week, and
    problems due a second look."""
    today = today or date.today()
    return {
        "interviews": rounds.upcoming(today),
        "practice_due": [practice_json(p) for p in practice.due(today)],
    }


# --- stories ------------------------------------------------------------------


def story_json(s) -> dict:
    return {**asdict(s), "theme_list": s.theme_list}


def handle_list_stories(stories) -> dict:
    return {"stories": [story_json(s) for s in stories.all()],
            "themes": [{"theme": t, "count": n} for t, n in stories.themes()]}


def handle_create_story(stories, body: dict) -> dict:
    fields = {k: v for k, v in body.items() if k != "title"}
    return _try(lambda: {"story": story_json(stories.create(str(body.get("title", "")), **fields))})


def handle_update_story(stories, story_id: str, body: dict) -> dict:
    return _try(lambda: {"story": story_json(stories.update(story_id, body))})


def handle_delete_story(stories, story_id: str) -> dict:
    return _try(lambda: stories.delete(story_id) or {"ok": True})


# --- practice -----------------------------------------------------------------


def practice_json(p, today: date | None = None) -> dict:
    today = today or date.today()
    nxt = p.next_review()
    return {**asdict(p), "next_review": nxt, "due": bool(nxt) and nxt <= today.isoformat()}


def handle_list_practice(practice, today: date | None = None) -> dict:
    today = today or date.today()
    return {"problems": [practice_json(p, today) for p in practice.all()],
            "coverage": practice.coverage(),
            "due_count": len(practice.due(today))}


def handle_add_problem(practice, body: dict) -> dict:
    return _try(lambda: {"problem": practice_json(practice.add(
        str(body.get("title", "")), str(body.get("url", "")), str(body.get("difficulty", "medium")),
        str(body.get("topic", "")), str(body.get("outcome", "solo")), str(body.get("solved_on", ""))))})


def handle_review_problem(practice, problem_id: str, body: dict) -> dict:
    return _try(lambda: {"problem": practice_json(
        practice.mark_reviewed(problem_id, outcome=str(body.get("outcome", ""))))})


def handle_delete_problem(practice, problem_id: str) -> dict:
    return _try(lambda: practice.delete(problem_id) or {"ok": True})


# --- offers -------------------------------------------------------------------


def offer_json(o, company: str = "", role: str = "") -> dict:
    return {**asdict(o), "first_year": o.first_year, "company": company, "role": role}


def handle_list_offers(offers, jobs) -> dict:
    names = {a.id: a for a in jobs.all()}
    return {"offers": [offer_json(o, names[o.application_id].company, names[o.application_id].role)
                       for o in offers.all() if o.application_id in names],
            "candidates": [{"id": a.id, "company": a.company, "role": a.role}
                           for a in names.values() if a.stage == "offer"]}


def handle_save_offer(offers, application_id: str, body: dict) -> dict:
    return _try(lambda: {"offer": asdict(offers.save(application_id, body))})


def handle_delete_offer(offers, application_id: str) -> dict:
    offers.delete(application_id)
    return {"ok": True}
