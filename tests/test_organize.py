"""Projects and conversations. Pure SQLite, no network or API key."""

import pytest

from mindtrail.organize.conversations import ConversationStore, title_from_question
from mindtrail.organize.db import initialize
from mindtrail.organize.projects import ProjectStore


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    initialize(path)
    return path


@pytest.fixture
def projects(db):
    return ProjectStore(db)


@pytest.fixture
def chats(db):
    return ConversationStore(db)


# --- projects ---------------------------------------------------------


def test_created_project_is_retrievable(projects):
    created = projects.create("Career")

    assert projects.get(created.id).name == "Career"


def test_project_name_is_trimmed(projects):
    assert projects.create("  Career  ").name == "Career"


def test_blank_project_name_is_rejected(projects):
    with pytest.raises(ValueError):
        projects.create("   ")


def test_projects_are_listed_case_insensitively_by_name(projects):
    projects.create("zebra")
    projects.create("Apple")

    assert [p.name for p in projects.all()] == ["Apple", "zebra"]


def test_renaming_a_project(projects):
    project = projects.create("Old")

    projects.rename(project.id, "New")

    assert projects.get(project.id).name == "New"


def test_renaming_a_missing_project_raises(projects):
    with pytest.raises(ValueError, match="no such project"):
        projects.rename("nonexistent", "New")


def test_deleting_a_missing_project_raises(projects):
    with pytest.raises(ValueError, match="no such project"):
        projects.delete("nonexistent")


# --- conversations ----------------------------------------------------


def test_created_conversation_starts_unpinned_and_read(chats):
    created = chats.create("My chat")

    assert created.pinned is False
    assert created.unread is False
    assert created.project_id is None


def test_renaming_a_conversation(chats):
    chat = chats.create("Old title")

    chats.rename(chat.id, "New title")

    assert chats.get(chat.id).title == "New title"


def test_blank_conversation_title_is_rejected(chats):
    chat = chats.create("Title")

    with pytest.raises(ValueError):
        chats.rename(chat.id, "  ")


def test_long_titles_are_truncated(chats):
    chat = chats.create("t")

    chats.rename(chat.id, "x" * 500)

    assert len(chats.get(chat.id).title) == 60


def test_pinning_and_unpinning(chats):
    chat = chats.create("t")

    chats.set_pinned(chat.id, True)
    assert chats.get(chat.id).pinned is True

    chats.set_pinned(chat.id, False)
    assert chats.get(chat.id).pinned is False


def test_marking_unread_and_read(chats):
    chat = chats.create("t")

    chats.set_unread(chat.id, True)
    assert chats.get(chat.id).unread is True

    chats.set_unread(chat.id, False)
    assert chats.get(chat.id).unread is False


def test_moving_a_conversation_into_a_project(chats, projects):
    project = projects.create("Career")
    chat = chats.create("t")

    chats.move(chat.id, project.id)

    assert chats.get(chat.id).project_id == project.id


def test_moving_a_conversation_back_out_of_a_project(chats, projects):
    project = projects.create("Career")
    chat = chats.create("t", project_id=project.id)

    chats.move(chat.id, None)

    assert chats.get(chat.id).project_id is None


def test_pinned_conversations_sort_first(chats):
    chats.create("first")
    second = chats.create("second")

    chats.set_pinned(second.id, True)

    assert [c.title for c in chats.all()][0] == "second"


def test_mutating_a_missing_conversation_raises(chats):
    with pytest.raises(ValueError, match="no such conversation"):
        chats.set_pinned("nonexistent", True)


def test_deleting_a_conversation_removes_it(chats):
    chat = chats.create("t")

    chats.delete(chat.id)

    assert chats.get(chat.id) is None


def test_in_project_filters_correctly(chats, projects):
    project = projects.create("Career")
    filed = chats.create("filed", project_id=project.id)
    chats.create("unfiled")

    assert [c.id for c in chats.in_project(project.id)] == [filed.id]


def test_in_project_none_returns_only_unfiled(chats, projects):
    project = projects.create("Career")
    chats.create("filed", project_id=project.id)
    unfiled = chats.create("unfiled")

    assert [c.id for c in chats.in_project(None)] == [unfiled.id]


# --- the destructive behaviour worth being sure about -----------------


def test_deleting_a_project_unfiles_its_chats_instead_of_deleting_them(
    chats, projects
):
    project = projects.create("Career")
    chat = chats.create("important research", project_id=project.id)

    projects.delete(project.id)

    survivor = chats.get(chat.id)
    assert survivor is not None, "deleting a project must not destroy its chats"
    assert survivor.project_id is None


# --- titles -----------------------------------------------------------


def test_title_comes_from_the_first_line_of_the_question():
    assert title_from_question("What is X?\nmore detail") == "What is X?"


def test_title_is_truncated():
    assert len(title_from_question("x" * 200)) == 60


def test_blank_question_gets_a_placeholder_title():
    assert title_from_question("   ") == "New chat"
