"""The reading list over saved links."""

import pytest

from mindtrail.memory.store import MemoryStore
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize
from mindtrail.web import admin_api


@pytest.fixture
def setup(tmp_path):
    db = str(tmp_path / "t.db")
    initialize(db)
    store = MemoryStore(path=str(tmp_path / "chroma"), collection="reading",
                        db_path=str(tmp_path / "m.db"))
    return store, AppState(db)


def test_unread_oldest_first_and_read_tracked_by_url(setup):
    store, state = setup
    store.add("Old article", "text", ["https://a.com/1"], kind="link", created_at="2026-09-01T00:00:00+00:00")
    store.add("New article", "text", ["https://b.com/2"], kind="link", created_at="2026-09-20T00:00:00+00:00")
    store.add("A research answer", "text", ["https://c.com"], kind="research")

    data = admin_api.handle_reading(store, state)
    assert [l["title"] for l in data["links"]] == ["Old article", "New article"]
    assert data["pick"]["title"] == "Old article" and data["unread"] == 2

    admin_api.handle_mark_read(state, {"url": "https://a.com/1"})
    data = admin_api.handle_reading(store, state)
    assert data["pick"]["title"] == "New article"
    assert [l["read"] for l in data["links"]] == [False, True]

    admin_api.handle_mark_read(state, {"url": "https://b.com/2"})
    assert admin_api.handle_reading(store, state)["pick"] is None
    assert "error" in admin_api.handle_mark_read(state, {})
