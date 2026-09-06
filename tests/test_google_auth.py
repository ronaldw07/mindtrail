"""Token persistence and refresh. No real Google credentials or network
calls anywhere here - `Credentials` objects are stubbed."""

import json
import os
import stat

import pytest

from mindtrail.integrations import google_auth


class StubCredentials:
    """Just enough of google.oauth2.credentials.Credentials for
    save/load/refresh to exercise, without a real OAuth token."""

    def __init__(self, token="access-token", refresh_token="refresh-token", expired=False):
        self.token = token
        self.refresh_token = refresh_token
        self.expired = expired
        self.refresh_calls = 0

    def to_json(self):
        return json.dumps(
            {
                "token": self.token,
                "refresh_token": self.refresh_token,
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",
                "scopes": google_auth.SCOPES,
            }
        )

    def refresh(self, request):
        self.refresh_calls += 1
        self.expired = False
        self.token = "refreshed-token"


def test_save_credentials_writes_the_file_mode_0600(tmp_path):
    path = str(tmp_path / "google_token.json")

    google_auth.save_credentials(StubCredentials(), path)

    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_save_credentials_creates_parent_directories(tmp_path):
    path = str(tmp_path / "nested" / "google_token.json")

    google_auth.save_credentials(StubCredentials(), path)

    assert os.path.exists(path)


def test_load_credentials_returns_none_when_never_connected(tmp_path):
    path = str(tmp_path / "google_token.json")

    assert google_auth.load_credentials(path) is None


def test_load_credentials_returns_none_for_a_corrupted_file(tmp_path):
    path = tmp_path / "google_token.json"
    path.write_text("not json")

    assert google_auth.load_credentials(str(path)) is None


def test_load_credentials_round_trips_a_saved_token(tmp_path):
    path = str(tmp_path / "google_token.json")
    google_auth.save_credentials(StubCredentials(token="abc", refresh_token="xyz"), path)

    loaded = google_auth.load_credentials(path)

    assert loaded is not None
    assert loaded.token == "abc"
    assert loaded.refresh_token == "xyz"


def test_ensure_fresh_refreshes_an_expired_token_and_persists_it(tmp_path):
    path = str(tmp_path / "google_token.json")
    creds = StubCredentials(expired=True)

    refreshed = google_auth.ensure_fresh(creds, path)

    assert refreshed.refresh_calls == 1
    assert refreshed.token == "refreshed-token"
    # Persisted, not just refreshed in memory - the next process to load
    # this file must see the new token, not the stale one.
    with open(path) as f:
        assert json.load(f)["token"] == "refreshed-token"


def test_ensure_fresh_leaves_a_valid_token_untouched(tmp_path):
    path = str(tmp_path / "google_token.json")
    creds = StubCredentials(expired=False)

    google_auth.ensure_fresh(creds, path)

    assert creds.refresh_calls == 0
    assert not os.path.exists(path)  # nothing written - nothing needed refreshing
