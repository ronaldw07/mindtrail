"""GitHub updates - every call stubbed, no network, no real token."""

from datetime import datetime, timedelta, timezone

import pytest

from mindtrail.integrations.github import GitHubError, GitHubUpdates, collect_updates
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize

NOW = datetime(2026, 10, 1, 17, tzinfo=timezone.utc)


def fake_get(token, path):
    if path == "/user":
        return {"login": "ronaldw07"}
    if path.startswith("/search/issues") and "review-requested" in path:
        return {"items": [{"title": "Fix tooltip", "repository_url": "https://api.github.com/repos/icssc/AntAlmanac",
                           "html_url": "https://github.com/icssc/AntAlmanac/pull/9", "updated_at": "x"}]}
    if path.startswith("/search/issues"):
        return {"items": [{"title": "Mobile selector", "repository_url": "https://api.github.com/repos/icssc/AntAlmanac",
                           "html_url": "https://github.com/icssc/AntAlmanac/pull/1", "updated_at": "y",
                           "draft": False, "comments": 3}]}
    if path.startswith("/user/repos"):
        return [{"name": "AntAlmanac", "full_name": "ronaldw07/AntAlmanac", "default_branch": "main"},
                {"name": "old", "full_name": "ronaldw07/old", "archived": True},
                {"name": "green", "full_name": "ronaldw07/green", "default_branch": "main"}]
    if "/ronaldw07/AntAlmanac/actions/runs" in path:
        return {"workflow_runs": [{"name": "Check and deploy new quarter", "conclusion": "failure",
                                   "html_url": "https://github.com/run/1", "updated_at": "z",
                                   "display_title": "Fall data"}]}
    if "/ronaldw07/green/actions/runs" in path:
        return {"workflow_runs": [{"name": "CI", "conclusion": "success"}]}
    raise AssertionError(f"unexpected call {path}")


@pytest.fixture
def state(tmp_path):
    db = str(tmp_path / "t.db")
    initialize(db)
    return AppState(db)


def test_collects_reviews_failing_ci_then_open_prs():
    data = collect_updates("t", fake_get)
    assert data["login"] == "ronaldw07"
    assert [i["kind"] for i in data["items"]] == ["review_requested", "ci_failing", "pr_open"]
    ci = data["items"][1]
    assert ci["title"] == "Check and deploy new quarter is failing on main"
    assert ci["repo"] == "ronaldw07/AntAlmanac"
    assert data["items"][0]["repo"] == "icssc/AntAlmanac"
    assert data["items"][2]["detail"] == "Open, waiting on review · 3 comments"


def test_no_token_is_not_connected_and_is_throttled(state):
    gh = GitHubUpdates(state, token_provider=lambda: "", get=fake_get, clock=lambda: NOW)
    assert gh.refresh()["connected"] is False
    assert gh.cached()["fetched_at"] == NOW.isoformat()


def test_errors_keep_the_last_good_items(state):
    gh = GitHubUpdates(state, token_provider=lambda: "t", get=fake_get, clock=lambda: NOW)
    gh.refresh()

    def broken(token, path):
        raise GitHubError("couldn't reach GitHub")
    failed = GitHubUpdates(state, token_provider=lambda: "t", get=broken, clock=lambda: NOW).refresh()
    assert failed["error"] and len(failed["items"]) == 3


def test_staleness_window(state):
    calls = []
    gh = GitHubUpdates(state, token_provider=lambda: "t", get=fake_get, clock=lambda: NOW)
    gh.refresh()
    gh.refresh = lambda: calls.append(1)
    gh.refresh_in_background_if_stale()
    assert calls == []
