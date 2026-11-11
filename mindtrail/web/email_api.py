"""Where a to-do came from: its job and the email that created it, with
a link to open that email in Gmail and a short preview fetched on demand
(bodies are never stored)."""

from __future__ import annotations

from mindtrail.integrations.gmail import web_url
from mindtrail.integrations.google_api import GoogleAuthError, GoogleFetchError
from mindtrail.organize.jobs import CLOSED

ACCOUNT_KEY = "gmail_account"   # the connected address, learned on the first preview
PREVIEW_CHARS = 700


def email_link(state, message_id: str) -> str:
    return web_url(message_id, state.get(ACCOUNT_KEY, "") if state else "")


def with_sources(data: dict, jobs, email_log, state) -> dict:
    """Each to-do in data["tasks"] with job {company, role, stage, closed}
    and email {id, subject, received_at, url} where it has them."""
    for t in data.get("tasks", []):
        app = jobs.get(t["application_id"]) if t.get("application_id") else None
        if app:
            t["job"] = {"company": app.company, "role": app.role, "stage": app.stage,
                        "closed": app.stage in CLOSED}
        seen = email_log.get(t["source_message_id"]) if t.get("source_message_id") else None
        if seen:
            t["email"] = {"id": seen["message_id"], "subject": seen["subject"],
                          "received_at": seen["received_at"], "url": email_link(state, seen["message_id"])}
    return data


def with_links(emails: list[dict], state) -> list[dict]:
    return [{**m, "url": email_link(state, m["message_id"])} for m in emails]


def handle_email(gmail, email_log, state, message_id: str) -> dict:
    """Sender, subject, date and the start of one email Mindtrail scanned."""
    if email_log.get(message_id) is None:
        return {"error": "that email isn't one Mindtrail has read"}
    try:
        message = gmail.get(message_id)
        if not state.get(ACCOUNT_KEY, ""):
            state.set(ACCOUNT_KEY, gmail.account())
    except (GoogleAuthError, GoogleFetchError) as exc:
        return {"error": f"Couldn't load the email: {exc}"}
    return {"subject": message.subject, "sender": message.sender, "received_at": message.received_at,
            "preview": message.body[:PREVIEW_CHARS], "url": email_link(state, message_id)}
