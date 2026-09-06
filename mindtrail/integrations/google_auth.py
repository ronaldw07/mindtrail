"""OAuth 2.0 for a read-only Google Calendar connection.

Uses google-auth and google-auth-oauthlib for the auth handshake and
token refresh only - subtle bugs in a hand-rolled token exchange are
security bugs, and these two libraries are Google's own, narrowly-scoped
implementations of exactly that. The actual Calendar API call in
google_calendar.py is a plain urllib request instead of pulling in the
full google-api-python-client, which would be a large, mostly-unused
dependency for one read-only endpoint.

Scope is calendar.readonly, always - this feature only ever reads a
calendar, and a broader scope would be a standing risk for no benefit.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from mindtrail import config

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# google-auth-oauthlib's InstalledAppFlow.run_local_server implements the
# RFC 8252 "loopback interface redirect" for installed apps: it starts a
# local HTTP server on 127.0.0.1, opens the consent screen with that
# server's address as the redirect_uri, and catches the authorization
# code when Google redirects back to it. This is the flow Google requires
# now that the out-of-band (urn:ietf:wg:oauth:2.0:oob) flow is retired.
# autogenerate_code_verifier=True (the library default as of 1.x, made
# explicit here since it is the whole point of using this flow) adds PKCE
# on top: a per-run secret is hashed into the authorization request and
# must be presented again at the token exchange, so a code intercepted in
# transit is useless without it.
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def default_token_path() -> str:
    """Sits beside the Chroma directory and the SQLite file (see
    organize/export.py's default_export_dir), but is never written *into*
    either of them. A refresh token is a live credential - anything
    stored in the SQLite file is one careless serializer away from ending
    up in a plaintext markdown backup a user might share or commit (see
    `mindtrail export`). Keeping it in its own file means export never
    has to remember to exclude it.
    """
    return str(Path(config.CHROMA_DIR).parent / "google_token.json")


def run_oauth_flow(client_id: str, client_secret: str) -> Credentials:
    """Run the installed-app + PKCE + loopback flow, opening a browser
    for consent and blocking until it completes. Raises whatever
    google-auth-oauthlib raises (e.g. the user closes the tab, or the
    client id/secret are wrong) - `mindtrail calendar connect` is the only
    caller and reports that directly rather than papering over it."""
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(
        client_config, scopes=SCOPES, autogenerate_code_verifier=True
    )
    return flow.run_local_server(port=0)


def save_credentials(creds: Credentials, path: str) -> None:
    """Write the refresh token to its own file, mode 0600, created with
    that mode rather than chmod'd afterward - os.open with a mode avoids
    the brief window where a chmod-after-write would leave the file
    world-readable.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    payload = creds.to_json()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(payload)


def load_credentials(path: str) -> Credentials | None:
    """None if never connected. A file that exists but fails to parse is
    treated the same way - the dashboard should show "connect Google
    Calendar" again, not crash on a corrupted token file."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    try:
        return Credentials.from_authorized_user_info(data, SCOPES)
    except ValueError:
        return None


def ensure_fresh(creds: Credentials, path: str) -> Credentials:
    """Refresh the access token if it has expired, persisting the new one
    so the next call doesn't refresh again. Raises
    google.auth.exceptions.RefreshError if the refresh token itself is
    expired or has been revoked in the Google Account's connected-apps
    settings - the caller (google_calendar.fetch_week_events) turns that
    into a "reconnect Google Calendar" prompt rather than letting it
    surface as a crash.
    """
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds, path)
    return creds
