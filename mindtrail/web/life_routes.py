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

from mindtrail.web import jobs_api, life_api

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
    return jobs_api.handle_list_jobs(deps.jobs, deps.tasks, deps.job_emails, deps.state)


@route("POST", "/api/jobs")
def _create_job(deps, args, body, query):
    return jobs_api.handle_create_job(deps.jobs, body)


@route("POST", "/api/jobs/sheet")
def _import_sheet(deps, args, body, query):
    return jobs_api.handle_import_sheet(deps.jobs, deps.state, deps.llm, deps.sheets, body)


@route("POST", "/api/jobs/scan")
def _scan_email(deps, args, body, query):
    return deps.scanner.scan()


@route("POST", "/api/jobs/link")
def _add_job_link(deps, args, body, query):
    return jobs_api.handle_add_job_link(deps.jobs, deps.llm, body)


@route("PATCH", f"/api/jobs/{_ID}")
def _update_job(deps, args, body, query):
    return jobs_api.handle_update_job(deps.jobs, deps.tasks, args[0], body)


@route("DELETE", f"/api/jobs/{_ID}")
def _delete_job(deps, args, body, query):
    return jobs_api.handle_delete_job(deps.jobs, args[0])


# --- areas ------------------------------------------------------------------


@route("GET", "/api/areas")
def _list_areas(deps, args, body, query):
    return life_api.handle_list_areas(deps.areas)


@route("POST", "/api/areas")
def _create_area(deps, args, body, query):
    return life_api.handle_create_area(deps.areas, body)


@route("PATCH", f"/api/areas/{_ID}")
def _update_area(deps, args, body, query):
    return life_api.handle_update_area(deps.areas, args[0], body)


@route("DELETE", f"/api/areas/{_ID}")
def _delete_area(deps, args, body, query):
    return life_api.handle_delete_area(deps.areas, args[0])


@route("PATCH", f"/api/projects/{_ID}/area")
def _set_project_area(deps, args, body, query):
    return life_api.handle_set_project_area(deps.areas, args[0], body)


# --- habits -----------------------------------------------------------------


@route("GET", "/api/habits")
def _list_habits(deps, args, body, query):
    return life_api.handle_list_habits(deps.habits, query.get("archived", [""])[0] == "1")


@route("POST", "/api/habits")
def _create_habit(deps, args, body, query):
    return life_api.handle_create_habit(deps.habits, body)


@route("PATCH", f"/api/habits/{_ID}")
def _update_habit(deps, args, body, query):
    return life_api.handle_update_habit(deps.habits, args[0], body)


@route("DELETE", f"/api/habits/{_ID}")
def _delete_habit(deps, args, body, query):
    return life_api.handle_delete_habit(deps.habits, args[0])


@route("POST", f"/api/habits/{_ID}/toggle")
def _toggle_habit(deps, args, body, query):
    return life_api.handle_toggle_habit(deps.habits, args[0], body)


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
