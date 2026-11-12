"""One journey step's page: its sub-steps (a route of one-off things to
do) and its daily goals (habits linked to the step). A step can be worked
on from Today while another journey is open, so these check the step is
in any of your journeys, not just the open one."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from mindtrail.advice import step_fill
from mindtrail.llm import LLMError
from mindtrail.organize.habits import DAILY
from mindtrail.organize.roadmaps import SHARED_KIND
from mindtrail.web.journey_api import _own_track, _settings, _try
from mindtrail.web.life_api import STREAK_LOOKBACK_DAYS, habit_json

DUE_SOON_DAYS = 2   # Today lists sub-steps due within this many days


def _own_step(journey, node_id: str):
    node = journey.nodes.get(node_id)
    track = journey.roadmaps.get(node.roadmap_id) if node else None
    if track is None or track.project_id not in {j["project_id"] for j in journey.all()}:
        raise ValueError("that step no longer exists")
    return node


def _own_task(journey, task_id: str):
    task = journey.tasks.get(task_id)
    if task is None:
        raise ValueError("that sub-step no longer exists")
    _own_step(journey, task.node_id)
    return task


def _goal_json(h, logs: dict, today: date, kind: str, name: str) -> dict:
    """A daily goal, with what it serves: {kind: step|path|journey, name}."""
    return {**habit_json(h, logs.get(h.id, set()), today), "scope": {"kind": kind, "name": name}}


def _logs(habits, today: date) -> dict:
    return habits.logs_since(today - timedelta(days=STREAK_LOOKBACK_DAYS))


def _page(journey, habits, node_id: str, today: date | None = None) -> dict:
    """A step's page: its sub-steps, and every daily goal that applies to
    it - its own, its path's and its journey's."""
    today = today or date.today()
    goals = []
    if habits:
        node = journey.nodes.get(node_id)
        track = journey.roadmaps.get(node.roadmap_id)
        logs = _logs(habits, today)
        goals = ([_goal_json(h, logs, today, "step", node.title) for h in habits.for_node(node_id)]
                 + [_goal_json(h, logs, today, "path", track.name or track.goal) for h in habits.for_track(track.id)]
                 + [_goal_json(h, logs, today, "journey", journey.names().get(track.project_id, "Journey"))
                    for h in habits.for_journey(track.project_id)])
    return {"tasks": [asdict(t) for t in journey.tasks.for_node(node_id)], "goals": goals,
            "today": today.isoformat()}


def handle_journey_goals(journey, habits, today: date | None = None) -> dict:
    """The open journey's own daily goals and each path's, for its page."""
    def run():
        today_ = today or date.today()
        pid = _settings(journey)["project_id"]
        logs = _logs(habits, today_)
        shared, others = journey.tracks(pid)
        goals = [_goal_json(h, logs, today_, "journey", journey.names().get(pid, "Journey"))
                 for h in habits.for_journey(pid)]
        for track in ([shared] if shared else []) + others:
            goals += [_goal_json(h, logs, today_, "path", "Every path" if track is shared else track.name or track.goal)
                      | {"track_id": track.id} for h in habits.for_track(track.id)]
        return {"goals": goals, "today": today_.isoformat()}
    return _try(run)


def handle_list(journey, habits, node_id: str, today: date | None = None) -> dict:
    def run():
        _own_step(journey, node_id)
        return _page(journey, habits, node_id, today)
    return _try(run)


def _filled(fill, typed: str) -> tuple[dict, bool]:
    """What the model made of `typed`, or {} when the AI couldn't help."""
    if not typed.strip():
        return {}, False
    try:
        return fill(), True
    except (LLMError, ValueError):
        return {}, False


def _step_place(journey, node):
    track = journey.roadmaps.get(node.roadmap_id)
    return track.name, track.kind == SHARED_KIND


def handle_add(journey, node_id: str, body: dict, llm=None, today: date | None = None) -> dict:
    """With body fill and an AI, what they typed is filled out into a full
    sub-step using the step around it; without, it's saved as typed."""
    def run():
        node = _own_step(journey, node_id)
        typed = str(body.get("title", ""))
        made, filled = {}, False
        if body.get("fill") and llm is not None:
            name, shared = _step_place(journey, node)
            made, filled = _filled(lambda: step_fill.fill_sub_step(
                llm, node, name, shared, journey.tasks.for_node(node_id), typed, today or date.today()), typed)
        fields = {k: body.get(k, "") for k in ("title", "detail", "due", "needs", "unit")} | made
        task = journey.tasks.add(node_id, fields["title"], fields["detail"], fields["due"],
                                 fields["needs"], fields["unit"])
        return {"task": asdict(task), "filled": filled}
    return _try(run)


def _scope_target(journey, scope: str, node_id: str = "", track_id: str = "") -> dict:
    """{node_id|track_id|journey_id: id} for a goal serving a step, a path,
    or the journey a step or path is in (or the open journey)."""
    if scope == "step":
        return {"node_id": _own_step(journey, node_id).id}
    if scope == "path":
        track_id = track_id or _own_step(journey, node_id).roadmap_id
        return {"track_id": _own_track(journey, track_id).id}
    if scope == "journey":
        if node_id or track_id:
            track = _own_track(journey, track_id or _own_step(journey, node_id).roadmap_id)
            return {"journey_id": track.project_id}
        return {"journey_id": _settings(journey)["project_id"]}
    raise ValueError("a daily goal is for a step, a path or a journey")


def handle_add_goal(journey, habits, node_id: str, body: dict, llm=None) -> dict:
    """A daily goal is a habit for this step, its path or its whole
    journey (body scope, default the step): every day, or N a week. With
    body fill and an AI, the name, how often and scope come from what
    they typed and the step it's on."""
    def run():
        node = _own_step(journey, node_id)
        typed = str(body.get("name", ""))
        made, filled = {}, False
        if body.get("fill") and llm is not None:
            name, shared = _step_place(journey, node)
            made, filled = _filled(lambda: step_fill.fill_goal(llm, node, name, shared, typed), typed)
        fields = {"name": typed, "per_week": body.get("per_week") or DAILY,
                  "scope": body.get("scope") or "step"} | made
        target = _scope_target(journey, str(fields["scope"]), node_id=node_id,
                               track_id=str(body.get("track_id", "")))
        habit = habits.create(str(fields["name"]), int(fields["per_week"]), **target)
        return {"goal": asdict(habit), "filled": filled}
    return _try(run)


def handle_add_journey_goal(journey, habits, body: dict) -> dict:
    """A daily goal from the journey page: for the journey or one path."""
    def run():
        target = _scope_target(journey, str(body.get("scope") or "journey"), track_id=str(body.get("track_id", "")))
        habit = habits.create(str(body.get("name", "")), int(body.get("per_week") or DAILY), **target)
        return {"goal": asdict(habit)}
    return _try(run)


def handle_goal_scope(journey, habits, habit_id: str, body: dict) -> dict:
    """Move a daily goal to serve a step, a path or the whole journey."""
    def run():
        if habits.get(habit_id) is None:
            raise ValueError("that daily goal no longer exists")
        target = _scope_target(journey, str(body.get("scope", "")), node_id=str(body.get("node_id", "")),
                               track_id=str(body.get("track_id", "")))
        [(column, value)] = target.items()
        return {"goal": asdict(habits.set_scope(habit_id, column, value))}
    return _try(run)


def handle_update(journey, task_id: str, body: dict) -> dict:
    def run():
        task = _own_task(journey, task_id)
        fields = {k: body[k] for k in ("title", "detail", "done", "due", "needs", "unit", "result") if k in body}
        updated = journey.tasks.update(task_id, **fields)
        # Finishing the last sub-step finishes the step (and unticking reopens it).
        step = journey.sync_step_done(task.node_id) if "done" in fields else ""
        return {"task": asdict(updated), "step": step}
    return _try(run)


def handle_reorder(journey, node_id: str, body: dict) -> dict:
    def run():
        _own_step(journey, node_id)
        journey.tasks.reorder(node_id, [str(i) for i in body.get("order") or []])
        return {"ok": True}
    return _try(run)


def handle_clear(journey, node_id: str) -> dict:
    """Remove the unfinished sub-steps; done ones stay as a record."""
    def run():
        _own_step(journey, node_id)
        return {"removed": journey.tasks.clear_unfinished(node_id)}
    return _try(run)


def handle_delete(journey, task_id: str) -> dict:
    def run():
        _own_task(journey, task_id)
        journey.tasks.delete(task_id)
        return {"ok": True}
    return _try(run)


def handle_due(journey, today: date | None = None) -> dict:
    """Sub-steps overdue or due in the next couple of days, from every
    journey, for Today."""
    today = today or date.today()
    mine = {j["project_id"] for j in journey.all()}
    last = (today + timedelta(days=DUE_SOON_DAYS)).isoformat()
    return {"today": today.isoformat(), "journey_ids": sorted(mine),
            "tasks": [t for t in journey.tasks.due_by(last) if t["project_id"] in mine]}
