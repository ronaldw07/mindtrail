"""Life-dashboard endpoints through a real socket: routing, bodies, auth."""

from __future__ import annotations

import json

import pytest

from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.projects import ProjectStore
from mindtrail.web.auth import AuthState
from mindtrail.web.chat_server import Deps
from tests.test_auth import StubLLM, StubResearcher, live_server, request


@pytest.fixture
def deps(tmp_path):
    db = str(tmp_path / "test.db")
    initialize(db)
    # No MemoryStore: none of these routes touch memory, and Chroma
    # startup is most of this suite's runtime. /api/sidebar doesn't either.
    return Deps(
        researcher=StubResearcher(),
        store=None,
        projects=ProjectStore(db),
        chats=ConversationStore(db),
        llm=StubLLM(),
    )


@pytest.fixture
def port(monkeypatch, deps):
    monkeypatch.delenv("MINDTRAIL_TOKEN", raising=False)
    with live_server(deps, AuthState.for_host("127.0.0.1")) as p:
        yield p


def call(port, method, path, body=None):
    resp, raw = request(port, method, path, body)
    return resp.status, json.loads(raw) if raw else None


def test_job_and_task_lifecycle(port):
    status, created = call(port, "POST", "/api/jobs", {"company": "IBM", "role": "PM Intern"})
    assert status == 200
    app_id = created["application"]["id"]

    _, moved = call(port, "PATCH", f"/api/jobs/{app_id}", {"stage": "interview"})
    assert moved["application"]["stage"] == "interview"

    _, task = call(port, "POST", "/api/tasks", {
        "title": "Record interview", "due_date": "2026-10-07", "application_id": app_id,
    })
    task_id = task["task"]["id"]

    _, listing = call(port, "GET", "/api/jobs")
    (app,) = listing["applications"]
    assert [t["id"] for t in app["tasks"]] == [task_id]
    assert listing["counts"]["interviewing"] == 1

    call(port, "PATCH", f"/api/tasks/{task_id}", {"done": True})
    assert call(port, "GET", "/api/tasks")[1]["tasks"] == []
    assert len(call(port, "GET", "/api/tasks?all=1")[1]["tasks"]) == 1

    assert call(port, "DELETE", f"/api/jobs/{app_id}")[1] == {"ok": True}
    assert call(port, "GET", "/api/jobs")[1]["applications"] == []


def test_bad_input_comes_back_as_an_error_not_a_crash(port):
    assert "error" in call(port, "POST", "/api/jobs", {"company": ""})[1]
    assert "error" in call(port, "PATCH", "/api/jobs/nope", {"stage": "offer"})[1]
    assert "error" in call(port, "POST", "/api/tasks", {
        "title": "x", "application_id": "missing"})[1]
    assert "error" in call(port, "POST", "/api/tasks", {"title": "x", "due_date": "tmrw"})[1]


def test_existing_routes_still_reach_the_old_handlers(port):
    status, sidebar = call(port, "GET", "/api/sidebar")
    assert status == 200 and "projects" in sidebar


def test_life_routes_require_login_when_a_token_is_set(monkeypatch, deps):
    monkeypatch.setenv("MINDTRAIL_TOKEN", "secret")
    with live_server(deps, AuthState.for_host("0.0.0.0")) as p:
        for method, path in (("GET", "/api/jobs"), ("POST", "/api/tasks"),
                             ("PATCH", "/api/tasks/x"), ("DELETE", "/api/jobs/x")):
            resp, _ = request(p, method, path, {})
            assert resp.status == 401, (method, path)
