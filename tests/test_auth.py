"""Auth: shared token, session cookie, fail-closed bind rules.

Runs a real ChatHandler behind a real socket (like the existing chat
server smoke test), because the behavior under test is HTTP status codes
and Set-Cookie headers - exactly what a pure-function test can't see.
"""

from __future__ import annotations

import http.client
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

import pytest

from mindtrail.ingest.researcher import Research
from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.web import auth
from mindtrail.web.auth import AuthState
from mindtrail.web.chat_server import Deps, make_handler, run_chat_server


class StubResearcher:
    def research_and_store(self, query, conversation_id="", instructions="", profile=""):
        return Research(
            query=query, summary="ok", sources=("http://a.com",), recalled=(), tokens=1
        )


class StubLLM:
    """Deps.llm is only touched by routes this suite doesn't exercise."""


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    initialize(path)
    return path


@pytest.fixture
def deps(tmp_path, db):
    return Deps(
        researcher=StubResearcher(),
        store=MemoryStore(path=str(tmp_path / "chroma"), collection="testcol"),
        projects=ProjectStore(db),
        chats=ConversationStore(db),
        llm=StubLLM(),
        profile=ProfileStore(db),
        roadmaps=RoadmapStore(db),
        roadmap_nodes=RoadmapNodeStore(db),
    )


@contextmanager
def live_server(deps, auth_state):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(deps, auth_state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        payload = None
        hdrs = dict(headers or {})
        if body is not None:
            import json

            payload = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        resp_body = resp.read()
        return resp, resp_body
    finally:
        conn.close()


# --- host + token resolution -------------------------------------------


def test_unset_token_and_loopback_requires_no_auth(monkeypatch):
    monkeypatch.delenv("MINDTRAIL_TOKEN", raising=False)

    state = AuthState.for_host("127.0.0.1")

    assert state.config.required is False


def test_unset_token_and_localhost_hostname_requires_no_auth(monkeypatch):
    monkeypatch.delenv("MINDTRAIL_TOKEN", raising=False)

    state = AuthState.for_host("localhost")

    assert state.config.required is False


def test_unset_token_and_non_loopback_host_refuses_to_start(monkeypatch):
    monkeypatch.delenv("MINDTRAIL_TOKEN", raising=False)

    with pytest.raises(ValueError, match="MINDTRAIL_TOKEN"):
        AuthState.for_host("0.0.0.0")


def test_run_chat_server_refuses_0_0_0_0_without_token(monkeypatch, deps):
    monkeypatch.delenv("MINDTRAIL_TOKEN", raising=False)

    with pytest.raises(ValueError, match="MINDTRAIL_TOKEN"):
        run_chat_server(deps, port=0, open_browser=False, host="0.0.0.0")


def test_set_token_requires_auth_regardless_of_host(monkeypatch):
    monkeypatch.setenv("MINDTRAIL_TOKEN", "secret")

    loopback = AuthState.for_host("127.0.0.1")
    lan = AuthState.for_host("0.0.0.0")

    assert loopback.config.required is True
    assert lan.config.required is True


# --- unset token + loopback: byte-for-byte identical to today -----------


def test_no_token_loopback_every_route_behaves_as_before(monkeypatch, deps):
    monkeypatch.delenv("MINDTRAIL_TOKEN", raising=False)
    state = AuthState.for_host("127.0.0.1")

    with live_server(deps, state) as port:
        resp, body = request(port, "GET", "/")
        assert resp.status == 200
        assert b"<html" in body.lower() or b"<!doctype" in body.lower()

        resp, body = request(port, "GET", "/api/sidebar")
        assert resp.status == 200

        resp, _ = request(port, "GET", "/nonexistent")
        assert resp.status == 404

        resp, _ = request(port, "POST", "/login", {"token": "whatever"})
        assert resp.status == 404  # no such route exists when auth is off


# --- set token: everything gated -----------------------------------------


def test_api_without_cookie_is_401(monkeypatch, deps):
    monkeypatch.setenv("MINDTRAIL_TOKEN", "secret")
    state = AuthState.for_host("0.0.0.0")

    with live_server(deps, state) as port:
        resp, _ = request(port, "GET", "/api/sidebar")
        assert resp.status == 401


def test_root_without_cookie_serves_login_page_not_401(monkeypatch, deps):
    monkeypatch.setenv("MINDTRAIL_TOKEN", "secret")
    state = AuthState.for_host("0.0.0.0")

    with live_server(deps, state) as port:
        resp, body = request(port, "GET", "/")
        assert resp.status == 200
        assert b"token" in body.lower()


def test_wrong_token_is_rejected(monkeypatch, deps):
    monkeypatch.setenv("MINDTRAIL_TOKEN", "secret")
    state = AuthState.for_host("0.0.0.0")

    with live_server(deps, state) as port:
        resp, _ = request(port, "POST", "/login", {"token": "nope"})
        assert resp.status == 401
        assert resp.getheader("Set-Cookie") is None


def test_correct_token_sets_cookie_and_unlocks_api(monkeypatch, deps):
    monkeypatch.setenv("MINDTRAIL_TOKEN", "secret")
    state = AuthState.for_host("0.0.0.0")

    with live_server(deps, state) as port:
        resp, _ = request(port, "POST", "/login", {"token": "secret"})
        assert resp.status == 200
        cookie = resp.getheader("Set-Cookie")
        assert cookie is not None
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie
        assert "Secure" not in cookie  # plain HTTP request, no TLS signal

        session_cookie = cookie.split(";")[0]
        resp, body = request(
            port, "GET", "/api/sidebar", headers={"Cookie": session_cookie}
        )
        assert resp.status == 200


def test_forged_cookie_is_401(monkeypatch, deps):
    monkeypatch.setenv("MINDTRAIL_TOKEN", "secret")
    state = AuthState.for_host("0.0.0.0")

    with live_server(deps, state) as port:
        resp, _ = request(
            port,
            "GET",
            "/api/sidebar",
            headers={"Cookie": f"{auth.SESSION_COOKIE_NAME}=made-up-value"},
        )
        assert resp.status == 401


def test_repeated_failed_logins_are_rate_limited(monkeypatch, deps):
    monkeypatch.setenv("MINDTRAIL_TOKEN", "secret")
    state = AuthState.for_host("0.0.0.0")

    with live_server(deps, state) as port:
        statuses = []
        for _ in range(auth.MAX_ATTEMPTS_BEFORE_BACKOFF + 2):
            resp, _ = request(port, "POST", "/login", {"token": "nope"})
            statuses.append(resp.status)

        assert statuses[: auth.MAX_ATTEMPTS_BEFORE_BACKOFF] == (
            [401] * auth.MAX_ATTEMPTS_BEFORE_BACKOFF
        )
        assert statuses[-1] == 429

        # Even the *correct* token is refused while locked out - a shared
        # secret with unlimited guesses is not a secret.
        resp, _ = request(port, "POST", "/login", {"token": "secret"})
        assert resp.status == 429


# --- other verbs / methods honor auth too --------------------------------


def test_patch_and_delete_require_auth_too(monkeypatch, deps):
    monkeypatch.setenv("MINDTRAIL_TOKEN", "secret")
    state = AuthState.for_host("0.0.0.0")

    with live_server(deps, state) as port:
        resp, _ = request(port, "PATCH", "/api/conversations/x", {"title": "y"})
        assert resp.status == 401

        resp, _ = request(port, "DELETE", "/api/conversations/x")
        assert resp.status == 401


# --- constant-time comparison --------------------------------------------


def test_token_check_uses_hmac_compare_digest(monkeypatch):
    calls = []
    real_compare = auth.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real_compare(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)

    config = auth.AuthConfig(token="secret", required=True)
    assert config.check("secret") is True
    assert config.check("wrong") is False

    assert calls == [("secret", "secret"), ("secret", "wrong")]


def test_token_check_never_uses_plain_equality_on_missing_token():
    # No token configured -> check() must short-circuit to False without
    # ever calling compare_digest(None, ...), which would raise.
    config = auth.AuthConfig(token=None, required=False)
    assert config.check("anything") is False
