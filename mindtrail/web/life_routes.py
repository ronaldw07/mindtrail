"""Route table for the life-dashboard endpoints (jobs, tasks, and later
habits, journal, ...).

chat_server.py's do_GET/do_POST are long if/elif chains. Rather than
grow them by a branch per endpoint, everything added for the life
dashboard is matched here by (method, path regex) and chat_server only
asks "is this one of yours?" once per request.

Each handler takes (deps, path_args, body, query) and returns a dict.
"""

from __future__ import annotations

import re

from mindtrail.web import jobs_api

ROUTES: list[tuple[str, re.Pattern, object]] = []


def route(method: str, pattern: str):
    def register(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return register


def find(method: str, path: str):
    """(handler, path_args) for a matching route, or None."""
    for m, pattern, fn in ROUTES:
        if m != method:
            continue
        match = pattern.match(path)
        if match:
            return fn, match.groups()
    return None


_ID = r"([A-Za-z0-9-]+)"


# --- jobs -------------------------------------------------------------------


@route("GET", "/api/jobs")
def _list_jobs(deps, args, body, query):
    return jobs_api.handle_list_jobs(deps.jobs, deps.tasks, deps.job_emails)


@route("POST", "/api/jobs")
def _create_job(deps, args, body, query):
    return jobs_api.handle_create_job(deps.jobs, body)


@route("POST", "/api/jobs/link")
def _add_job_link(deps, args, body, query):
    return jobs_api.handle_add_job_link(deps.jobs, deps.llm, body)


@route("PATCH", f"/api/jobs/{_ID}")
def _update_job(deps, args, body, query):
    return jobs_api.handle_update_job(deps.jobs, deps.tasks, args[0], body)


@route("DELETE", f"/api/jobs/{_ID}")
def _delete_job(deps, args, body, query):
    return jobs_api.handle_delete_job(deps.jobs, args[0])


# --- tasks ------------------------------------------------------------------


@route("GET", "/api/tasks")
def _list_tasks(deps, args, body, query):
    return jobs_api.handle_list_tasks(deps.tasks, query.get("all", [""])[0] == "1")


@route("POST", "/api/tasks")
def _add_task(deps, args, body, query):
    return jobs_api.handle_add_task(deps.tasks, body)


@route("PATCH", f"/api/tasks/{_ID}")
def _update_task(deps, args, body, query):
    return jobs_api.handle_update_task(deps.tasks, args[0], body)


@route("DELETE", f"/api/tasks/{_ID}")
def _delete_task(deps, args, body, query):
    return jobs_api.handle_delete_task(deps.tasks, args[0])
