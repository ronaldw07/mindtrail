"""Request handlers for job applications and tasks.

Same shape as web/api.py: pure functions over the stores, returning
JSON-ready dicts, with errors as {"error": ...} rather than exceptions.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from mindtrail.ingest.job_posting import add_from_link
from mindtrail.organize.jobs import CLOSED, PIPELINE, STAGES, Application, JobStore
from mindtrail.organize.tasks import Task, TaskStore

RESPONDED_STAGES = ("oa", "interview", "offer", "rejected")
WEEK_DAYS = 7


def task_json(task: Task) -> dict:
    return asdict(task)


def application_json(app: Application, tasks: list[Task], emails: list[dict]) -> dict:
    return {**asdict(app), "tasks": [task_json(t) for t in tasks], "emails": emails}


def pipeline_counts(apps: list[Application], today: date) -> dict:
    """Applied this week, response rate, interviews pending."""
    week_ago = (today - timedelta(days=WEEK_DAYS)).isoformat()
    sent = [a for a in apps if a.stage not in ("saved", "withdrawn")]
    responded = [a for a in sent if a.stage in RESPONDED_STAGES]
    return {
        "applied_this_week": sum(1 for a in sent if a.applied_at and a.applied_at > week_ago),
        "response_rate": round(len(responded) / len(sent), 2) if sent else 0.0,
        "interviewing": sum(1 for a in apps if a.stage == "interview"),
        "total": len(apps),
    }


def handle_list_jobs(jobs: JobStore, tasks: TaskStore, emails_for=None) -> dict:
    """Every application with its tasks and (once Gmail is connected) the
    subject/date of each matched email. `emails_for(app_id)` is optional
    so this works before the email scan exists or is connected."""
    apps = jobs.all()
    return {
        "stages": list(STAGES),
        "pipeline": list(PIPELINE),
        "closed": list(CLOSED),
        "applications": [
            application_json(a, tasks.for_application(a.id), emails_for(a.id) if emails_for else [])
            for a in apps
        ],
        "counts": pipeline_counts(apps, date.today()),
    }


def handle_create_job(jobs: JobStore, body: dict) -> dict:
    try:
        app = jobs.create(
            str(body.get("company", "")),
            role=str(body.get("role", "")),
            url=str(body.get("url", "")),
            location=str(body.get("location", "")),
            stage=str(body.get("stage", "applied")),
            applied_at=str(body.get("applied_at", "")),
            deadline=str(body.get("deadline", "")),
            notes=str(body.get("notes", "")),
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"application": application_json(app, [], [])}


def handle_add_job_link(jobs: JobStore, llm, body: dict, fetch=None) -> dict:
    kwargs = {"fetch": fetch} if fetch else {}
    try:
        app, warning = add_from_link(
            jobs, llm, str(body.get("url", "")), stage=str(body.get("stage", "applied")), **kwargs
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"application": application_json(app, [], []), "warning": warning}


def handle_update_job(jobs: JobStore, tasks: TaskStore, app_id: str, body: dict) -> dict:
    try:
        app = jobs.update(app_id, body)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"application": application_json(app, tasks.for_application(app.id), [])}


def handle_delete_job(jobs: JobStore, app_id: str) -> dict:
    try:
        jobs.delete(app_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


def handle_list_tasks(tasks: TaskStore, include_done: bool = False) -> dict:
    items = tasks.all() if include_done else tasks.open()
    return {"tasks": [task_json(t) for t in items]}


def handle_add_task(tasks: TaskStore, body: dict) -> dict:
    try:
        task = tasks.add(
            str(body.get("title", "")),
            due_date=str(body.get("due_date", "")),
            application_id=body.get("application_id") or None,
            area_id=str(body.get("area_id", "") or ""),
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"task": task_json(task)}


def handle_update_task(tasks: TaskStore, task_id: str, body: dict) -> dict:
    try:
        task = tasks.update(task_id, body)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"task": task_json(task)}


def handle_delete_task(tasks: TaskStore, task_id: str) -> dict:
    try:
        tasks.delete(task_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}
