"""Connecting Google from Settings instead of the terminal.

The OAuth consent screen opens in the browser on this machine (the same
loopback flow `mindtrail google connect` uses) while a background thread
waits for it; the page polls status() to see how it went.
"""

from __future__ import annotations

import threading

from mindtrail import config
from mindtrail.integrations.google_auth import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_SCOPE,
    GMAIL_SCOPE,
    SHEETS_SCOPE,
    default_token_path,
    has_scope,
    load_credentials,
    run_oauth_flow,
    save_credentials,
)

ACCESS = (("calendar", CALENDAR_SCOPE), ("gmail", GMAIL_SCOPE), ("sheets", SHEETS_SCOPE),
          ("calendar_write", CALENDAR_EVENTS_SCOPE))


class GoogleConnector:
    def __init__(self, token_path: str | None = None, flow=run_oauth_flow):
        self._token_path = token_path or default_token_path()
        self._flow = flow
        self._lock = threading.Lock()
        self._connecting = False
        self._error = ""

    def status(self) -> dict:
        creds = load_credentials(self._token_path)
        return {
            "configured": bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET),
            "connected": creds is not None,
            "access": {name: bool(creds and has_scope(creds, scope)) for name, scope in ACCESS},
            "connecting": self._connecting,
            "error": self._error,
        }

    def start(self) -> dict:
        if not (config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET):
            return {"error": "add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env first"}
        with self._lock:
            if self._connecting:
                return {"started": True}
            self._connecting, self._error = True, ""
        threading.Thread(target=self._run, daemon=True, name="google-connect").start()
        return {"started": True}

    def _run(self) -> None:
        try:
            creds = self._flow(config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET)
            save_credentials(creds, self._token_path)
        except Exception as exc:  # noqa: BLE001 - reported on the Settings page
            self._error = f"{type(exc).__name__}: {exc}"
        finally:
            self._connecting = False
