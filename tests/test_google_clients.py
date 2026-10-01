"""Gmail, Sheets, and the shared Google GET helper. No network: urlopen
and credentials are stubbed throughout."""

import base64
import io
import json
import urllib.error

import pytest

from mindtrail.integrations import google_api, google_auth
from mindtrail.integrations.gmail import GmailClient, body_text, parse_message
from mindtrail.integrations.google_api import GoogleAuthError, GoogleFetchError
from mindtrail.integrations.google_sheets import SheetsClient, parse_sheet_link


def _write_token(path, scopes):
    path.write_text(json.dumps({
        "token": "t", "refresh_token": "r", "client_id": "i", "client_secret": "s",
        "token_uri": "https://oauth2.googleapis.com/token", "scopes": scopes,
    }))
    return str(path)


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


# --- scopes -----------------------------------------------------------------


class GrantedCreds:
    def __init__(self, granted, requested):
        self.granted_scopes = granted
        self.scopes = requested

    def to_json(self):
        return json.dumps({"token": "t", "refresh_token": "r", "client_id": "i",
                           "client_secret": "s", "scopes": self.scopes})


def test_saved_token_records_granted_not_requested_scopes(tmp_path):
    path = str(tmp_path / "tok.json")
    google_auth.save_credentials(
        GrantedCreds(google_auth.CALENDAR_SCOPE, google_auth.SCOPES), path)
    creds = google_auth.load_credentials(path)
    assert google_auth.has_scope(creds, google_auth.CALENDAR_SCOPE)
    assert not google_auth.has_scope(creds, google_auth.GMAIL_SCOPE)


def test_an_old_calendar_only_token_still_loads_with_its_own_scope(tmp_path):
    path = _write_token(tmp_path / "tok.json", [google_auth.CALENDAR_SCOPE])
    creds = google_auth.load_credentials(path)
    assert creds.scopes == [google_auth.CALENDAR_SCOPE]


def test_credentials_for_explains_what_to_do(tmp_path):
    with pytest.raises(GoogleAuthError, match="isn't connected"):
        google_api.credentials_for(google_auth.GMAIL_SCOPE, "Gmail", str(tmp_path / "none"))
    path = _write_token(tmp_path / "tok.json", [google_auth.CALENDAR_SCOPE])
    with pytest.raises(GoogleAuthError, match="allow Gmail"):
        google_api.credentials_for(google_auth.GMAIL_SCOPE, "Gmail", path)


# --- get_json error mapping ---------------------------------------------------


class FreshCreds:
    token = "t"
    expired = False
    refresh_token = "r"


def _http_error(code, message):
    body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())
    return urllib.error.HTTPError("u", code, "err", {}, body)


@pytest.mark.parametrize("code,message,error,match", [
    (403, "Gmail API has not been used in project 1 before or it is disabled.",
     GoogleFetchError, "isn't enabled"),
    (401, "Invalid Credentials", GoogleAuthError, "denied"),
    (500, "backend", GoogleFetchError, "500"),
])
def test_http_errors_map_to_actionable_messages(monkeypatch, code, message, error, match):
    def fail(request, timeout):
        raise _http_error(code, message)
    monkeypatch.setattr(google_api.urllib.request, "urlopen", fail)
    with pytest.raises(error, match=match):
        google_api.get_json(FreshCreds(), "unused", "https://x")


def test_get_json_sends_the_bearer_token_and_params(monkeypatch):
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def ok(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.headers["Authorization"]
        return Resp(b'{"ok": 1}')
    monkeypatch.setattr(google_api.urllib.request, "urlopen", ok)
    assert google_api.get_json(FreshCreds(), "unused", "https://x", {"q": "a b"}) == {"ok": 1}
    assert seen == {"url": "https://x?q=a+b", "auth": "Bearer t"}


# --- gmail ------------------------------------------------------------------


def test_parse_message_prefers_plain_text_and_truncates():
    raw = {
        "id": "m1", "internalDate": "1790000000000", "snippet": "snip",
        "payload": {
            "headers": [{"name": "Subject", "value": "Your OA"},
                        {"name": "From", "value": "IBM <jobs@ibm.com>"}],
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
                {"mimeType": "text/plain", "body": {"data": _b64("plain " * 1000)}},
            ],
        },
    }
    msg = parse_message(raw)
    assert (msg.id, msg.subject, msg.sender) == ("m1", "Your OA", "IBM <jobs@ibm.com>")
    assert msg.body.startswith("plain plain") and len(msg.body) == 1500
    assert msg.received_at


def test_html_only_body_becomes_text_and_empty_falls_back_to_snippet():
    html = {"mimeType": "text/html", "body": {"data": _b64("<b>Interview</b> invite")}}
    assert "Interview invite" in body_text(html)
    assert parse_message({"id": "x", "snippet": "s", "payload": {}}).body == "s"


def test_search_ids_pages_until_the_limit(tmp_path):
    token = _write_token(tmp_path / "tok.json", google_auth.SCOPES)
    pages = iter([
        {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "p2"},
        {"messages": [{"id": "c"}], "nextPageToken": "p3"},
    ])
    calls = []

    def get(creds, path, url, params):
        calls.append(params)
        return next(pages)
    ids = GmailClient(token, get=get).search_ids("interview", limit=3)
    assert ids == ["a", "b", "c"]
    assert calls[1]["pageToken"] == "p2" and calls[1]["maxResults"] == 1


# --- sheets -----------------------------------------------------------------


def test_parse_sheet_link_reads_id_and_tab():
    link = "https://docs.google.com/spreadsheets/d/abc_123-X/edit#gid=42"
    assert parse_sheet_link(link) == ("abc_123-X", 42)
    assert parse_sheet_link("https://docs.google.com/spreadsheets/d/abc/edit") == ("abc", None)
    with pytest.raises(ValueError):
        parse_sheet_link("https://evil.com/spreadsheets/d/abc")


def test_rows_reads_the_tab_the_link_points_at(tmp_path):
    token = _write_token(tmp_path / "tok.json", google_auth.SCOPES)
    urls = []

    def get(creds, path, url, params):
        urls.append(url)
        if url.endswith("/abc"):
            return {"sheets": [{"properties": {"sheetId": 0, "title": "2025"}},
                               {"properties": {"sheetId": 42, "title": "Fall '26"}}]}
        return {"values": [["Company", "Role"], ["IBM", 7]]}
    rows = SheetsClient(token, get=get).rows("https://docs.google.com/spreadsheets/d/abc/edit#gid=42")
    assert rows == [["Company", "Role"], ["IBM", "7"]]
    assert urls[1].endswith("/values/%27Fall%20%27%2726%27")
