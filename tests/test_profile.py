"""Profile store tests. Pure SQLite, no network or API key."""

import pytest

from mindtrail.organize.db import initialize
from mindtrail.organize.profile import ProfileStore


@pytest.fixture
def profile(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return ProfileStore(path)


def test_empty_profile_is_empty(profile):
    assert profile.get().is_empty


def test_saved_content_is_retrievable(profile):
    profile.save("CS student at UCI")

    assert profile.get().content == "CS student at UCI"


def test_saved_content_is_no_longer_empty(profile):
    profile.save("something")

    assert not profile.get().is_empty


def test_saving_again_overwrites(profile):
    profile.save("first draft")
    profile.save("second draft")

    assert profile.get().content == "second draft"


def test_content_is_trimmed(profile):
    profile.save("  padded  ")

    assert profile.get().content == "padded"


def test_content_is_truncated_to_the_limit(profile):
    profile.save("x" * 10000)

    assert len(profile.get().content) == 4000


def test_saving_sets_updated_at(profile):
    saved = profile.save("x")

    assert saved.updated_at
    assert profile.get().updated_at == saved.updated_at


def test_whitespace_only_content_is_empty(profile):
    profile.save("   ")

    assert profile.get().is_empty
