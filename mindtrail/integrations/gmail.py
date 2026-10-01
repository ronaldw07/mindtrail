"""Read-only Gmail: search for messages and read one.

Only the job scan (advice/job_scan.py) calls this. Bodies are cut to
BODY_CHARS before anything else sees them - the scan only needs enough
of an email to classify it, and less text sent to the model is less of
your inbox leaving the machine.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime

from mindtrail.ingest.fetch import html_to_text
from mindtrail.integrations.google_api import credentials_for, get_json
from mindtrail.integrations.google_auth import GMAIL_SCOPE

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
BODY_CHARS = 1500
PAGE_SIZE = 100


@dataclass(frozen=True)
class Message:
    id: str
    sender: str
    subject: str
    received_at: str  # local ISO timestamp
    body: str


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _find_part(payload: dict, mime: str) -> str:
    if payload.get("mimeType") == mime and payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        found = _find_part(part, mime)
        if found:
            return found
    return ""


def body_text(payload: dict) -> str:
    """Plain-text part if there is one, else the HTML part as text."""
    text = _find_part(payload, "text/plain")
    if text:
        return " ".join(text.split())[:BODY_CHARS]
    html = _find_part(payload, "text/html")
    return html_to_text(html, max_chars=BODY_CHARS) if html else ""


def parse_message(raw: dict) -> Message:
    payload = raw.get("payload", {})
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}
    try:
        received = datetime.fromtimestamp(int(raw.get("internalDate", "0")) / 1000).astimezone()
        received_at = received.isoformat(timespec="seconds")
    except (ValueError, OverflowError, OSError):
        received_at = ""
    return Message(
        id=raw.get("id", ""),
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        received_at=received_at,
        body=body_text(payload) or raw.get("snippet", ""),
    )


class GmailClient:
    """`get` is injectable so tests never touch the network."""

    def __init__(self, token_path: str | None = None, get=get_json):
        self._token_path = token_path
        self._get = get

    def _creds(self):
        return credentials_for(GMAIL_SCOPE, "Gmail", self._token_path)

    def search_ids(self, query: str, limit: int) -> list[str]:
        """Message ids matching a Gmail search, newest first, at most `limit`."""
        creds, path = self._creds()
        ids: list[str] = []
        page_token = None
        while len(ids) < limit:
            params = {"q": query, "maxResults": min(PAGE_SIZE, limit - len(ids))}
            if page_token:
                params["pageToken"] = page_token
            data = self._get(creds, path, f"{GMAIL_API}/messages", params)
            ids.extend(m["id"] for m in data.get("messages", []) if m.get("id"))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return ids[:limit]

    def get(self, message_id: str) -> Message:
        creds, path = self._creds()
        raw = self._get(creds, path, f"{GMAIL_API}/messages/{message_id}", {"format": "full"})
        return parse_message(raw)
