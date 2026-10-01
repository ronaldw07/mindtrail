"""One authenticated GET against a Google REST API, for Gmail and Sheets.

Plain urllib for the same reason as google_calendar.py: two read-only
endpoints don't justify google-api-python-client. Errors are split into
"the user has to reconnect" and "something else went wrong", because the
UI says different things for each - and the most likely first-run
mistake (an API not enabled in the Cloud project) gets a message that
says exactly that.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

from google.auth.exceptions import RefreshError

from mindtrail.integrations.google_auth import (
    default_token_path,
    ensure_fresh,
    has_scope,
    load_credentials,
)

TIMEOUT_SECONDS = 15


class GoogleAuthError(RuntimeError):
    """Not connected, missing a scope, or the token was revoked."""


class GoogleFetchError(RuntimeError):
    """Network trouble or an API error that reconnecting won't fix."""


def credentials_for(scope: str, what: str, token_path: str | None = None):
    """Loaded credentials that carry `scope`, or GoogleAuthError saying
    what to do. `what` names the feature for the message ("Gmail")."""
    path = token_path or default_token_path()
    creds = load_credentials(path)
    if creds is None:
        raise GoogleAuthError("Google isn't connected - run: mindtrail google connect")
    if not has_scope(creds, scope):
        raise GoogleAuthError(
            f"reconnect Google to allow {what} - run: mindtrail google connect"
        )
    return creds, path


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
        return str(body.get("error", {}).get("message", "")) or str(exc)
    except (ValueError, OSError, AttributeError):
        return str(exc)


def get_json(creds, token_path: str, url: str, params: dict | None = None) -> dict:
    try:
        creds = ensure_fresh(creds, token_path)
    except RefreshError as exc:
        raise GoogleAuthError(
            "Google sign-in expired - run: mindtrail google connect"
        ) from exc

    full = f"{url}?{urlencode(params, doseq=True)}" if params else url
    request = urllib.request.Request(full, headers={"Authorization": f"Bearer {creds.token}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = _error_message(exc)
        if "has not been used" in message or "is disabled" in message:
            raise GoogleFetchError(
                f"that API isn't enabled in your Google Cloud project: {message}"
            ) from exc
        if exc.code in (401, 403):
            raise GoogleAuthError(f"Google denied the request: {message}") from exc
        raise GoogleFetchError(f"Google request failed ({exc.code}): {message}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise GoogleFetchError(f"couldn't reach Google: {exc}") from exc
