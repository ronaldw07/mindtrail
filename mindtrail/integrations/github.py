"""GitHub updates for Today: your open PRs, reviews you've been asked
for, and failing CI on your own repos.

Read-only by construction - every call here is a GET. The token comes
from GITHUB_TOKEN if set, otherwise from the GitHub CLI's existing login
(`gh auth token`), so there's usually nothing to set up. It's held in
memory only, never written anywhere.

Fetched in the background at most every CACHE_MINUTES; Today reads the
cached copy and never waits on GitHub.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

API = "https://api.github.com"
CACHE_KEY = "github_cache"
CACHE_MINUTES = 30
TIMEOUT_SECONDS = 15
REPOS_CHECKED = 10
MAX_ITEMS = 8


class GitHubError(RuntimeError):
    pass


def default_token() -> str:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        return token
    gh = shutil.which("gh")
    if not gh:
        return ""
    try:
        result = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _get(token: str, path: str) -> dict | list:
    request = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mindtrail",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise GitHubError("GitHub rejected the token - run: gh auth login") from exc
        raise GitHubError(f"GitHub request failed ({exc.code})") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise GitHubError(f"couldn't reach GitHub: {exc}") from exc


def _repo_name(repository_url: str) -> str:
    """owner/name - a fork and its upstream share a name, and a PR into
    each is a separate item worth telling apart."""
    return "/".join(repository_url.rstrip("/").split("/")[-2:])


def collect_updates(token: str, get=_get) -> dict:
    """{"login", "items": [...]} - review requests first, then failing CI,
    then your own open PRs, newest first within each."""
    login = get(token, "/user").get("login", "")
    q = lambda query: get(token, "/search/issues?q=" + quote(query) + "&sort=updated&per_page=10")

    reviews = [{
        "kind": "review_requested", "title": i["title"], "repo": _repo_name(i["repository_url"]),
        "url": i["html_url"], "updated_at": i["updated_at"],
        "detail": "Your review was requested",
    } for i in q("is:pr is:open review-requested:@me").get("items", [])]

    prs = []
    for i in q("is:pr is:open author:@me").get("items", []):
        waiting = "Draft" if i.get("draft") else "Open, waiting on review"
        if i.get("comments"):
            waiting += f" · {i['comments']} comment" + ("s" if i["comments"] != 1 else "")
        prs.append({"kind": "pr_open", "title": i["title"], "repo": _repo_name(i["repository_url"]),
                    "url": i["html_url"], "updated_at": i["updated_at"], "detail": waiting})

    failing = []
    repos = get(token, f"/user/repos?affiliation=owner&sort=pushed&per_page={REPOS_CHECKED}")
    for repo in repos if isinstance(repos, list) else []:
        # Forks are included on purpose: a fork's scheduled workflow
        # failing quietly is exactly the kind of thing this should surface.
        if repo.get("archived"):
            continue
        branch = repo.get("default_branch", "main")
        runs = get(token, f"/repos/{repo['full_name']}/actions/runs?branch={quote(branch)}&per_page=1")
        latest = (runs.get("workflow_runs") or [None])[0]
        if latest and latest.get("conclusion") == "failure":
            failing.append({
                "kind": "ci_failing", "title": f"{latest.get('name') or 'CI'} is failing on {branch}",
                "repo": repo["full_name"], "url": latest.get("html_url", repo.get("html_url", "")),
                "updated_at": latest.get("updated_at", ""),
                "detail": "Latest run failed: " + (latest.get("display_title") or "")[:100],
            })

    items = reviews + failing + prs
    return {"login": login, "items": items[:MAX_ITEMS]}


class GitHubUpdates:
    def __init__(self, state, token_provider=default_token, get=_get,
                 clock=lambda: datetime.now(timezone.utc)):
        self._state = state
        self._token = token_provider
        self._get = get
        self._clock = clock
        self._lock = threading.Lock()

    def cached(self) -> dict:
        return self._state.get(CACHE_KEY) or {}

    def refresh(self) -> dict:
        token = self._token()
        if not token:
            result = {"connected": False, "fetched_at": self._clock().isoformat()}
            self._state.set(CACHE_KEY, result)
            return result
        with self._lock:
            try:
                data = collect_updates(token, self._get)
            except GitHubError as exc:
                result = {**self.cached(), "error": str(exc), "fetched_at": self._clock().isoformat()}
            else:
                result = {"connected": True, **data, "fetched_at": self._clock().isoformat()}
            self._state.set(CACHE_KEY, result)
            return result

    def refresh_in_background_if_stale(self) -> None:
        try:
            fetched = datetime.fromisoformat(self.cached()["fetched_at"])
            stale = self._clock() - fetched > timedelta(minutes=CACHE_MINUTES)
        except (KeyError, ValueError, TypeError):
            stale = True
        if stale and not self._lock.locked():
            threading.Thread(target=self.refresh, daemon=True, name="github-refresh").start()
