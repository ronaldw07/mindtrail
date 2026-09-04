"""Shared-token auth for the chat server.

This is a single-user local tool, so the design is deliberately minimal:
one shared secret from `MINDTRAIL_TOKEN`, one in-memory session table, one
in-memory login rate limiter. No accounts, no password hashing, nothing
persisted to disk.

The rule that matters: fail closed, never fail open.

- Token set -> every request needs a valid session, on any host.
- Token unset + loopback bind -> no auth. Local use must not grow a login
  step, and loopback is not reachable from outside the machine anyway.
- Token unset + non-loopback bind (0.0.0.0, a LAN IP) -> refuse to start.
  Silently downgrading to loopback would be just as wrong as starting
  unauthenticated: a user who asked for 0.0.0.0 needs to be told why they
  did not get it, not have the bind quietly changed under them.
"""

from __future__ import annotations

import hmac
import os
import secrets
import time
from dataclasses import dataclass, field

# Hosts that are only reachable from this machine. Anything else (a LAN
# IP, 0.0.0.0, a hostname) is treated as potentially reachable by someone
# else and requires a token.
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

SESSION_COOKIE_NAME = "mindtrail_session"

# How many failed /login attempts a single client address gets before it
# is locked out, and for how long. A shared secret with unlimited guesses
# is not a secret; this is deliberately simple in-memory backoff rather
# than a dependency.
MAX_ATTEMPTS_BEFORE_BACKOFF = 5
BACKOFF_SECONDS = 30.0


def is_loopback(host: str) -> bool:
    return host in LOOPBACK_HOSTS


@dataclass(frozen=True)
class AuthConfig:
    """Resolved once at server startup from MINDTRAIL_TOKEN + bind host."""

    token: str | None
    required: bool

    def check(self, candidate: str) -> bool:
        """Constant-time compare. `==` on strings short-circuits on the
        first mismatched character, which leaks the token's length and
        prefix through response timing - hmac.compare_digest does not."""
        if not self.token:
            return False
        return hmac.compare_digest(self.token, candidate)


def resolve_auth_config(host: str) -> AuthConfig:
    """Read MINDTRAIL_TOKEN and decide whether auth is required for this
    bind host. Raises ValueError when starting would fail open."""
    token = os.environ.get("MINDTRAIL_TOKEN") or None
    if token:
        return AuthConfig(token=token, required=True)
    if is_loopback(host):
        return AuthConfig(token=None, required=False)
    raise ValueError(
        f"refusing to bind {host!r} without MINDTRAIL_TOKEN set: every "
        "note, chat, document, and roadmap would be world-readable and "
        "world-writable to anyone who can reach this address. Set "
        "MINDTRAIL_TOKEN, or bind to 127.0.0.1 for local-only use."
    )


class SessionStore:
    """In-memory session ids created by a successful /login.

    Restarting the process clears this and logs everyone out. That is
    correct and simple for a tool meant to be used by one person: there
    is no session data worth persisting across a restart, and it avoids
    needing to invalidate anything on disk.
    """

    def __init__(self) -> None:
        self._ids: set[str] = set()

    def create(self) -> str:
        session_id = secrets.token_urlsafe(32)
        self._ids.add(session_id)
        return session_id

    def is_valid(self, session_id: str | None) -> bool:
        # An unknown id covers both a forged cookie and one from a
        # session table that no longer exists (e.g. after a restart) -
        # there is no separate "expired" state to distinguish from that.
        return bool(session_id) and session_id in self._ids


class LoginRateLimiter:
    """Per-client-address backoff on failed logins.

    A plain list of failure timestamps per address, pruned to the
    current window on each check. No dependency, no background thread.
    """

    def __init__(
        self,
        max_attempts: int = MAX_ATTEMPTS_BEFORE_BACKOFF,
        window_seconds: float = BACKOFF_SECONDS,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}

    def is_blocked(self, address: str) -> bool:
        now = time.monotonic()
        recent = [
            t for t in self._failures.get(address, [])
            if now - t < self._window_seconds
        ]
        self._failures[address] = recent
        return len(recent) >= self._max_attempts

    def record_failure(self, address: str) -> None:
        self._failures.setdefault(address, []).append(time.monotonic())

    def record_success(self, address: str) -> None:
        self._failures.pop(address, None)


@dataclass
class AuthState:
    """Everything a running server needs for auth, bundled once so the
    handler factory takes one extra argument instead of three."""

    config: AuthConfig
    sessions: SessionStore = field(default_factory=SessionStore)
    limiter: LoginRateLimiter = field(default_factory=LoginRateLimiter)

    @classmethod
    def for_host(cls, host: str) -> AuthState:
        """Raises ValueError if this host cannot start safely - see
        resolve_auth_config. Call this before binding any socket."""
        return cls(config=resolve_auth_config(host))


def parse_session_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == SESSION_COOKIE_NAME:
            return value
    return None


def build_session_cookie_header(session_id: str, secure: bool) -> str:
    """httpOnly + SameSite=Strict always; Secure only when the request
    arrived over HTTPS. Always setting Secure would break plain-HTTP LAN
    use (the common case for this tool); never setting it would be wrong
    behind a TLS-terminating proxy."""
    attrs = [
        f"{SESSION_COOKIE_NAME}={session_id}",
        "HttpOnly",
        "SameSite=Strict",
        "Path=/",
    ]
    if secure:
        attrs.append("Secure")
    return "; ".join(attrs)


# Minimal, self-contained login page - no dependency on /static/*, so it
# works even though static assets are also gated behind auth.
LOGIN_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>mindtrail</title>
<style>
  body { font-family: system-ui, sans-serif; display: flex; align-items: center;
         justify-content: center; height: 100vh; margin: 0; background: #14161a; color: #e8e8ea; }
  form { display: flex; flex-direction: column; gap: 0.75rem; width: 260px; }
  input, button { padding: 0.55rem 0.7rem; font-size: 1rem; border-radius: 6px; border: 1px solid #3a3d44; }
  input { background: #1e2126; color: inherit; }
  button { background: #4a7dff; color: #fff; border: none; cursor: pointer; }
  #error { color: #f88; min-height: 1.2em; font-size: 0.85rem; }
</style>
</head>
<body>
  <form id="login">
    <label for="token">Access token</label>
    <input id="token" type="password" autocomplete="current-password" autofocus>
    <button type="submit">Enter</button>
    <div id="error"></div>
  </form>
  <script>
    document.getElementById("login").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const token = document.getElementById("token").value;
      const res = await fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      if (res.ok) {
        location.reload();
      } else {
        const msg = res.status === 429 ? "too many attempts, wait a bit" : "wrong token";
        document.getElementById("error").textContent = msg;
      }
    });
  </script>
</body>
</html>"""
