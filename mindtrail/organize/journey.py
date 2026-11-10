"""Journeys: each one a project whose roadmaps are its paths (tracks).

You can have several - a Career journey, a Health journey - and one is
open at a time; every handler works on the open one. A journey's kind
decides how it starts: "career" gets the CS recruiting anchors and the
internship tracks below, anything else starts with one path aimed at
the purpose you gave it.

A journey is an ordinary project. Each track (AI/ML, SWE, ...) is one
of its roadmaps, and one more roadmap, kind SHARED_KIND, holds the steps
every track has in common - classes, Year 1, recruiting seasons. Steps
carry a school term (organize/terms.py), which is what the Timeline lays
out by.

On top of that sit three small tables: what you wrote about each past
term, the model's reviews of a year, and suggestions waiting for you to
accept or dismiss. Nothing here ever changes a track by itself - a
suggestion only becomes a step through `accept_suggestion`.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass

from mindtrail.organize.db import connect, now_iso
from mindtrail.organize.roadmaps import (
    SHARED_KIND, RoadmapNodeStore, RoadmapStore, duplicate_roadmap,
)
from mindtrail.organize.terms import clean_term

STATE_KEY = "journey"          # the open journey's settings
LIST_KEY = "journeys"          # every journey's settings, in creation order
KINDS = ("career", "general")
MAX_NAME = 60
MAX_PURPOSE = 500
YEARS = 4
MAX_TEXT = 6000
SUGGESTION_KINDS = ("add_step", "add_done", "mark_done")
SOURCES = ("review", "mindtrail", "gmail", "calendar", "gemini", "paste", "canvas", "phone")

SCHOOL_PATH = ("School", "Classes, grades and deadlines")
SCHOOL_ADDED_KEY = "journeySchoolAdded"
DEFAULT_TRACKS = (
    SCHOOL_PATH,
    ("AI/ML", "Land an AI/ML engineering internship"),
    ("SWE", "Land a software engineering internship"),
    ("Product Eng", "Land a product engineering internship"),
)

# Dated facts about recruiting, proposed (never accepted) so each one is
# yours to keep or reject. Everything about what you actually did comes
# from you, in the Year 1 reflections.
ANCHORS = (
    (1, "fall", "Apply for summer internships",
     "Big-tech summer postings open around August to October; apply early."),
    (2, "fall", "Apply for summer internships",
     "The main recruiting season for next summer."),
    (3, "fall", "Apply for summer internships or new-grad roles",
     "Return offers and new-grad applications start now."),
    (1, "fall", "UC transfer application (if transferring)",
     "Due November 30. Reject this step if you're staying."),
)


@dataclass(frozen=True)
class Suggestion:
    id: str
    project_id: str
    kind: str
    roadmap_id: str
    node_id: str
    title: str
    detail: str
    term: str
    reason: str
    source: str
    status: str
    created_at: str


def _norm(title: str) -> str:
    return " ".join(title.lower().split())


class JourneyStore:
    def __init__(self, path: str | None, state, roadmaps: RoadmapStore, nodes: RoadmapNodeStore):
        self._path = path
        self._state = state
        self.roadmaps = roadmaps
        self.nodes = nodes

    # --- which project is the journey ---------------------------------------

    def all(self) -> list[dict]:
        """Every journey whose project still exists. A database from before
        there could be several holds just the one, under STATE_KEY; it
        becomes the Career journey."""
        saved = self._state.get(LIST_KEY)
        if saved is None:
            single = self._state.get(STATE_KEY)
            saved = [{"kind": "career", "purpose": "", **single}] if single and single.get("project_id") else []
        with connect(self._path) as conn:
            alive = {r[0] for r in conn.execute("SELECT id FROM projects")}
        return [j for j in saved if j.get("project_id") in alive]

    def settings(self) -> dict | None:
        """The open journey: {"project_id", "start_year", "kind", "purpose"},
        or None if there are none. Falls back to the first journey if the
        open one's project has been deleted."""
        journeys = self.all()
        if not journeys:
            return None
        active = (self._state.get(STATE_KEY) or {}).get("project_id")
        return next((j for j in journeys if j["project_id"] == active), journeys[0])

    def select(self, project_id: str) -> dict:
        chosen = next((j for j in self.all() if j["project_id"] == project_id), None)
        if chosen is None:
            raise ValueError("no such journey")
        self._state.set(STATE_KEY, chosen)
        return chosen

    def update(self, projects, project_id: str, name: str | None = None,
               purpose: str | None = None) -> dict:
        """Rename a journey or change what it's for."""
        journeys = self.all()
        target = next((j for j in journeys if j["project_id"] == project_id), None)
        if target is None:
            raise ValueError("no such journey")
        if name is not None:
            if not name.strip():
                raise ValueError("a journey needs a name")
            projects.rename(project_id, name.strip()[:MAX_NAME])
        if purpose is not None:
            target = {**target, "purpose": purpose.strip()[:MAX_PURPOSE]}
        updated = [target if j["project_id"] == project_id else j for j in journeys]
        self._state.set(LIST_KEY, updated)
        if (self._state.get(STATE_KEY) or {}).get("project_id") == project_id:
            self._state.set(STATE_KEY, target)
        return target

    def setup(self, projects, start_year: int, copy_roadmap_ids: list[str] = (),
              name: str = "", purpose: str = "", kind: str = "career") -> dict:
        """Create a journey and open it. A career journey gets the shared
        track with its recruiting anchors and the default internship
        tracks; any other kind gets one path aimed at its purpose. Either
        way, each roadmap in `copy_roadmap_ids` is copied in as its own
        track (the originals stay untouched)."""
        if not 2000 <= start_year <= 2100:
            raise ValueError("start year looks wrong")
        if kind not in KINDS:
            raise ValueError("unknown kind of journey")
        name, purpose = name.strip()[:MAX_NAME], purpose.strip()[:MAX_PURPOSE]
        if kind != "career" and not name:
            raise ValueError("a journey needs a name")
        project = projects.create(name or f"CS journey {start_year}–{start_year + YEARS}")
        shared = self.roadmaps.create("Shared by every track", project.id, name="Every track",
                                      kind=SHARED_KIND)
        if kind == "career":
            for year_offset, season, title, detail in ANCHORS:
                fall = start_year + year_offset
                term = f"{fall}-fall" if season == "fall" else f"{fall + 1}-{season}"
                self.nodes.add(shared.id, title, detail, status="proposed", term=term)
            for track_name, goal in DEFAULT_TRACKS:
                self.roadmaps.create(goal, project.id, name=track_name)
        else:
            self.roadmaps.create(purpose or name, project.id, name="Main path")
        for roadmap_id in copy_roadmap_ids:
            source = self.roadmaps.get(roadmap_id)
            if source is None:
                raise ValueError(f"no such roadmap: {roadmap_id}")
            duplicate_roadmap(self.roadmaps, self.nodes, roadmap_id,
                              _copy_name(projects, source), project_id=project.id)
        saved = {"project_id": project.id, "start_year": start_year, "kind": kind, "purpose": purpose}
        self._state.set(LIST_KEY, self.all() + [saved])
        self._state.set(STATE_KEY, saved)
        self._state.set(SCHOOL_ADDED_KEY, sorted(set(self._state.get(SCHOOL_ADDED_KEY) or []) | {project.id}))
        return saved

    def school_track(self, project_id: str):
        """The School path of a journey, or None."""
        _, others = self.tracks(project_id)
        return next((r for r in others if r.name == SCHOOL_PATH[0]), None)

    def add_school_paths(self) -> None:
        """Give career journeys made before School was a default path one.
        Once per journey, so deleting it keeps it deleted."""
        done = set(self._state.get(SCHOOL_ADDED_KEY) or [])
        for j in self.all():
            pid = j["project_id"]
            if j.get("kind", "career") != "career" or pid in done:
                continue
            if self.school_track(pid) is None:
                self.roadmaps.create(SCHOOL_PATH[1], pid, name=SCHOOL_PATH[0])
            done.add(pid)
        self._state.set(SCHOOL_ADDED_KEY, sorted(done))

    def tracks(self, project_id: str) -> tuple:
        """(shared roadmap or None, [other roadmaps])."""
        all_maps = self.roadmaps.list_for_project(project_id)
        shared = next((r for r in all_maps if r.kind == SHARED_KIND), None)
        return shared, [r for r in all_maps if r.kind != SHARED_KIND]

    # --- reflections ----------------------------------------------------------

    def reflections(self, project_id: str) -> dict[str, str]:
        with connect(self._path) as conn:
            rows = conn.execute("SELECT term, text FROM journey_reflections WHERE project_id = ?",
                                (project_id,)).fetchall()
        return {r["term"]: r["text"] for r in rows}

    def set_reflection(self, project_id: str, term: str, text: str) -> None:
        term = clean_term(term)
        if not term:
            raise ValueError("a reflection needs a term")
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO journey_reflections (project_id, term, text, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(project_id, term) DO UPDATE SET "
                "text = excluded.text, updated_at = excluded.updated_at",
                (project_id, term, str(text or "")[:MAX_TEXT], now_iso()),
            )

    # --- reviews --------------------------------------------------------------

    def add_review(self, project_id: str, year: int, body: dict) -> dict:
        review = {"id": str(uuid.uuid4()), "year": year, "body": body, "created_at": now_iso()}
        with connect(self._path) as conn:
            conn.execute("INSERT INTO journey_reviews (id, project_id, year, body, created_at) "
                         "VALUES (?, ?, ?, ?, ?)",
                         (review["id"], project_id, year, json.dumps(body), review["created_at"]))
        return review

    def latest_reviews(self, project_id: str) -> dict[int, dict]:
        """year -> its newest review."""
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM journey_reviews WHERE project_id = ? "
                                "ORDER BY created_at", (project_id,)).fetchall()
        return {r["year"]: {"id": r["id"], "year": r["year"], "body": json.loads(r["body"]),
                            "created_at": r["created_at"]} for r in rows}

    # --- suggestions ----------------------------------------------------------

    def add_suggestion(self, project_id: str, source: str, kind: str, title: str = "",
                       detail: str = "", term: str = "", roadmap_id: str = "",
                       node_id: str = "", reason: str = "") -> Suggestion | None:
        """None when it repeats one already pending or dismissed - a
        suggestion you turned down shouldn't come back on the next scan."""
        if kind not in SUGGESTION_KINDS:
            raise ValueError(f"invalid suggestion kind: {kind}")
        if source not in SOURCES:
            raise ValueError(f"invalid source: {source}")
        title = " ".join(str(title).split())[:160]
        if kind != "mark_done" and not title:
            raise ValueError("a suggested step needs a title")
        try:
            term = clean_term(term)
        except ValueError:
            term = ""
        if kind != "mark_done" and self._already_a_step(project_id, title, term):
            return None
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT kind, title, node_id FROM journey_suggestions WHERE project_id = ? "
                "AND status != 'accepted'", (project_id,)).fetchall()
        for r in rows:
            same_node = kind == "mark_done" and r["kind"] == "mark_done" and r["node_id"] == node_id
            same_title = kind != "mark_done" and _norm(r["title"]) == _norm(title)
            if same_node or same_title:
                return None
        s = Suggestion(id=str(uuid.uuid4()), project_id=project_id, kind=kind,
                       roadmap_id=roadmap_id, node_id=node_id, title=title,
                       detail=str(detail)[:600], term=term, reason=str(reason)[:300],
                       source=source, status="pending", created_at=now_iso())
        with connect(self._path) as conn:
            conn.execute(
                "INSERT INTO journey_suggestions (id, project_id, kind, roadmap_id, node_id, "
                "title, detail, term, reason, source, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(asdict(s).values()))
        return s

    def _already_a_step(self, project_id: str, title: str, term: str) -> bool:
        """A step with this title is already on a track in this term (or the
        suggestion names no term) - whatever its status, so a step you
        skipped doesn't get suggested again either."""
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT n.title, n.term FROM roadmap_nodes n JOIN roadmaps r ON r.id = n.roadmap_id "
                "WHERE r.project_id = ?", (project_id,)).fetchall()
        return any(_norm(r["title"]) == _norm(title) and (not term or r["term"] == term) for r in rows)

    def pending(self, project_id: str) -> list[Suggestion]:
        with connect(self._path) as conn:
            rows = conn.execute("SELECT * FROM journey_suggestions WHERE project_id = ? "
                                "AND status = 'pending' ORDER BY created_at", (project_id,)).fetchall()
        return [Suggestion(**dict(r)) for r in rows]

    def get_suggestion(self, suggestion_id: str) -> Suggestion | None:
        with connect(self._path) as conn:
            row = conn.execute("SELECT * FROM journey_suggestions WHERE id = ?",
                               (suggestion_id,)).fetchone()
        return Suggestion(**dict(row)) if row else None

    def _set_status(self, suggestion_id: str, status: str) -> None:
        with connect(self._path) as conn:
            conn.execute("UPDATE journey_suggestions SET status = ? WHERE id = ?",
                         (status, suggestion_id))

    def dismiss_suggestion(self, suggestion_id: str) -> None:
        if self.get_suggestion(suggestion_id) is None:
            raise ValueError(f"no such suggestion: {suggestion_id}")
        self._set_status(suggestion_id, "dismissed")

    def accept_suggestion(self, suggestion_id: str, roadmap_id: str = "") -> str:
        """Apply it to its track and return the id of the step it touched.
        `roadmap_id` overrides which track a new step lands on."""
        s = self.get_suggestion(suggestion_id)
        if s is None or s.status != "pending":
            raise ValueError("that suggestion is no longer pending")
        if s.kind == "mark_done":
            if self.nodes.get(s.node_id) is None:
                raise ValueError("that step no longer exists")
            self.nodes.set_status(s.node_id, "done")
            node_id = s.node_id
        else:
            target = roadmap_id or s.roadmap_id
            track = self.roadmaps.get(target) if target else None
            if track is None or track.project_id != s.project_id:
                shared, _ = self.tracks(s.project_id)
                if shared is None:
                    raise ValueError("pick a track for this step")
                track = shared
            status = "done" if s.kind == "add_done" else "accepted"
            node_id = self.nodes.add(track.id, s.title, s.detail, status=status, term=s.term).id
        self._set_status(suggestion_id, "accepted")
        return node_id


def _copy_name(projects, source) -> str:
    if source.name:
        return f"{source.name} (copy)"[:60]
    project = projects.get(source.project_id) if source.project_id else None
    return f"From {project.name}"[:60] if project else "Copy"
