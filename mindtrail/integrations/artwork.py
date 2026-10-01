"""A public-domain painting for each day's brief, from the Art Institute
of Chicago's open-access collection.

Fetched once a day and cached on disk, so the Today view never waits on
the network after the first visit of the day and keeps working offline
(it falls back to the most recent cached painting). The hosts are fixed
constants here, never user input, so this uses plain urllib rather than
ingest/fetch.py's SSRF-hardened path - there is no attacker-chosen URL.

Never raises: no painting is a normal state, and the Today view shows a
plain header instead.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import quote

from mindtrail import config

SEARCH_URL = "https://api.artic.edu/api/v1/artworks/search"
IMAGE_URL = "https://www.artic.edu/iiif/2/{image_id}/full/1686,/0/default.jpg"
# AIC asks API clients to identify themselves, and its image server
# rejects Python's default User-Agent outright (403), so both are set.
HEADERS = {
    "AIC-User-Agent": "mindtrail (personal dashboard)",
    "User-Agent": "mindtrail/1.0 (personal dashboard)",
}
TIMEOUT_SECONDS = 20
MAX_IMAGE_BYTES = 8 * 1024 * 1024
CANDIDATES_KEY = "artwork_candidates"
CANDIDATES_MAX_AGE_DAYS = 30
KEEP_DAYS = 7
MIN_ASPECT = 1.25  # wide enough to sit behind a title like a banner

# Public-domain Impressionist landscape paintings - the register of the
# reference brief. artwork_type_id 1 is "Painting" in AIC's taxonomy.
QUERY = {
    "q": "landscape",
    "query": {"bool": {"must": [
        {"term": {"is_public_domain": True}},
        {"term": {"artwork_type_id": 1}},
        {"match": {"style_titles": "Impressionism"}},
    ]}},
    "limit": 100,
    "fields": "id,title,artist_title,date_display,image_id,thumbnail",
}


def default_cache_dir() -> str:
    return str(Path(config.CHROMA_DIR).parent / "artwork_cache")


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read(MAX_IMAGE_BYTES + 1)
    if len(body) > MAX_IMAGE_BYTES:
        raise ValueError("image too large")
    return body


def search_candidates(get=_get) -> list[dict]:
    items = []
    for page in (1, 2):
        params = quote(json.dumps({**QUERY, "page": page}))
        data = json.loads(get(f"{SEARCH_URL}?params={params}").decode("utf-8"))
        for a in data.get("data", []):
            thumb = a.get("thumbnail") or {}
            width, height = thumb.get("width") or 0, thumb.get("height") or 0
            if a.get("image_id") and height and width / height >= MIN_ASPECT:
                items.append({
                    "id": a["id"], "image_id": a["image_id"],
                    "title": a.get("title") or "Untitled",
                    "artist": a.get("artist_title") or "Unknown artist",
                    "date": a.get("date_display") or "",
                })
    return items


class ArtworkClient:
    def __init__(self, state, cache_dir: str | None = None, get=_get):
        self._state = state
        self._dir = Path(cache_dir or default_cache_dir())
        self._get = get

    def _candidates(self, today: date) -> list[dict]:
        cached = self._state.get(CANDIDATES_KEY) or {}
        try:
            age = (today - date.fromisoformat(cached.get("fetched", ""))).days
        except ValueError:
            age = None
        if cached.get("items") and age is not None and age < CANDIDATES_MAX_AGE_DAYS:
            return cached["items"]
        items = search_candidates(self._get)
        if items:
            self._state.set(CANDIDATES_KEY, {"fetched": today.isoformat(), "items": items})
        return items or cached.get("items", [])

    def _meta_path(self, day: str) -> Path:
        return self._dir / f"{day}.json"

    def image_path(self, day: str) -> Path | None:
        path = self._dir / f"{day}.jpg"
        return path if path.is_file() else None

    def _latest_cached(self) -> dict | None:
        metas = sorted(self._dir.glob("*.json"), reverse=True) if self._dir.is_dir() else []
        for meta in metas:
            day = meta.stem
            if self.image_path(day):
                return json.loads(meta.read_text(encoding="utf-8"))
        return None

    def _prune(self, today: date) -> None:
        for path in self._dir.glob("*.*"):
            try:
                age = (today - date.fromisoformat(path.stem)).days
            except ValueError:
                continue
            if age > KEEP_DAYS:
                path.unlink(missing_ok=True)

    def today(self, today: date | None = None) -> dict:
        """{"available", "day", "title", "artist", "date"} for today's
        painting, the newest cached one if today's can't be fetched, or
        {"available": False}."""
        today = today or date.today()
        day = today.isoformat()
        meta_path = self._meta_path(day)
        if meta_path.is_file() and self.image_path(day):
            return json.loads(meta_path.read_text(encoding="utf-8"))
        try:
            items = self._candidates(today)
            if not items:
                raise ValueError("no paintings found")
            pick = items[today.toordinal() % len(items)]
            image = self._get(IMAGE_URL.format(image_id=pick["image_id"]))
            if not image.startswith(b"\xff\xd8"):
                raise ValueError("not a JPEG")
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / f"{day}.jpg").write_bytes(image)
            meta = {"available": True, "day": day, "title": pick["title"],
                    "artist": pick["artist"], "date": pick["date"]}
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            self._prune(today)
            return meta
        except Exception:  # noqa: BLE001 - see module docstring: never raises
            return self._latest_cached() or {"available": False}
