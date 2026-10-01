"""Read-only Google Sheets: the rows of one tab, from a pasted link."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, urlparse

from mindtrail.integrations.google_api import credentials_for, get_json
from mindtrail.integrations.google_auth import SHEETS_SCOPE

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
_SHEET_ID = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


def parse_sheet_link(url: str) -> tuple[str, int | None]:
    """(spreadsheet id, tab gid or None) from a docs.google.com link."""
    parsed = urlparse(url.strip())
    if parsed.hostname != "docs.google.com":
        raise ValueError("paste a docs.google.com/spreadsheets link")
    match = _SHEET_ID.search(parsed.path)
    if not match:
        raise ValueError("that link doesn't point at a spreadsheet")
    gid = None
    for source in (parsed.fragment, parsed.query):
        values = parse_qs(source).get("gid")
        if values and values[0].isdigit():
            gid = int(values[0])
            break
    return match.group(1), gid


def _tab_title(meta: dict, gid: int | None) -> str:
    sheets = [s.get("properties", {}) for s in meta.get("sheets", [])]
    if not sheets:
        raise ValueError("that spreadsheet has no tabs")
    if gid is not None:
        for props in sheets:
            if props.get("sheetId") == gid:
                return props.get("title", "")
    return sheets[0].get("title", "")


class SheetsClient:
    def __init__(self, token_path: str | None = None, get=get_json):
        self._token_path = token_path
        self._get = get

    def rows(self, link: str) -> list[list[str]]:
        """Every row of the linked tab (the first tab if the link has no
        gid), as strings. Row 0 is normally the header."""
        sheet_id, gid = parse_sheet_link(link)
        creds, path = credentials_for(SHEETS_SCOPE, "Google Sheets", self._token_path)
        meta = self._get(creds, path, f"{SHEETS_API}/{sheet_id}",
                         {"fields": "sheets.properties(sheetId,title)"})
        title = _tab_title(meta, gid)
        # A quoted tab name is a valid A1 range covering the whole tab.
        a1 = quote("'" + title.replace("'", "''") + "'", safe="")
        data = self._get(creds, path, f"{SHEETS_API}/{sheet_id}/values/{a1}", None)
        return [[str(cell) for cell in row] for row in data.get("values", [])]
