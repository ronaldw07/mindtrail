"""Daily artwork: picking, caching, pruning, offline fallback - no network."""

import json
from datetime import date, timedelta

import pytest

from mindtrail.integrations.artwork import ArtworkClient, search_candidates
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize
from mindtrail.web import life_routes

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
DAY = date(2026, 10, 1)


def search_page(*artworks):
    return json.dumps({"data": list(artworks)}).encode()


def art(i, w=300, h=200, image=True):
    return {"id": i, "title": f"Painting {i}", "artist_title": "Monet", "date_display": "1890",
            "image_id": f"img{i}" if image else None, "thumbnail": {"width": w, "height": h}}


class FakeGet:
    def __init__(self, pages=None, image=JPEG, fail=False):
        self.pages = pages or [search_page(art(1), art(2)), search_page()]
        self.image, self.fail, self.calls = image, fail, []

    def __call__(self, url):
        self.calls.append(url)
        if self.fail:
            raise OSError("offline")
        if "search" in url:
            return self.pages[sum("search" in c for c in self.calls) - 1]
        return self.image


@pytest.fixture
def state(tmp_path):
    db = str(tmp_path / "t.db")
    initialize(db)
    return AppState(db)


def test_only_wide_paintings_with_images_are_candidates():
    get = FakeGet(pages=[search_page(art(1), art(2, 200, 300), art(3, image=False)), search_page()])
    assert [c["id"] for c in search_candidates(get)] == [1]


def test_fetches_once_a_day_then_serves_from_disk(tmp_path, state):
    get = FakeGet()
    client = ArtworkClient(state, str(tmp_path / "art"), get)
    first = client.today(DAY)
    calls = len(get.calls)
    assert first["available"] and first["artist"] == "Monet"
    assert client.today(DAY) == first and len(get.calls) == calls
    assert client.image_path(DAY.isoformat()).read_bytes() == JPEG


def test_candidate_list_is_reused_for_a_month(tmp_path, state):
    get = FakeGet()
    client = ArtworkClient(state, str(tmp_path / "art"), get)
    client.today(DAY)
    client.today(DAY + timedelta(days=1))
    assert sum("search" in c for c in get.calls) == 2  # two pages, once


def test_offline_falls_back_to_the_newest_cached_painting(tmp_path, state):
    client = ArtworkClient(state, str(tmp_path / "art"), FakeGet())
    yesterday = client.today(DAY - timedelta(days=1))
    offline = ArtworkClient(state, str(tmp_path / "art"), FakeGet(fail=True))
    assert offline.today(DAY) == yesterday


def test_nothing_cached_and_offline_is_unavailable_not_an_error(tmp_path, state):
    assert ArtworkClient(state, str(tmp_path / "art"), FakeGet(fail=True)).today(DAY) == {
        "available": False}


def test_a_non_jpeg_response_is_rejected(tmp_path, state):
    client = ArtworkClient(state, str(tmp_path / "art"), FakeGet(image=b"<html>error</html>"))
    assert client.today(DAY) == {"available": False}


def test_old_images_are_pruned(tmp_path, state):
    client = ArtworkClient(state, str(tmp_path / "art"), FakeGet())
    client.today(DAY - timedelta(days=10))
    client.today(DAY)
    assert client.image_path((DAY - timedelta(days=10)).isoformat()) is None
    assert client.image_path(DAY.isoformat()) is not None


def test_image_route_only_accepts_real_dates(tmp_path, state):
    class Deps:
        artwork = ArtworkClient(state, str(tmp_path / "art"), FakeGet())
    Deps.artwork.today(DAY)
    handler, _ = life_routes.find("GET", "/api/artwork/image")
    assert handler(Deps, (), {}, {"day": [DAY.isoformat()]}).body == JPEG
    for bad in ("../../etc/passwd", "2026-13-01", ""):
        assert handler(Deps, (), {}, {"day": [bad]}).status == 404
