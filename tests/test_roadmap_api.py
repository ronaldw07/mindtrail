"""Roadmap and profile HTTP handlers. Pure functions, model stubbed."""

import pytest

from mindtrail.llm import Completion, LLMError
from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.web import api


class StubLLM:
    def __init__(self, text, error=None):
        self._text = text
        self._error = error
        self.calls = 0
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=1800):
        self.calls += 1
        self.last_user_prompt = user
        if self._error:
            raise self._error
        return Completion(text=self._text, tokens=5, model="stub")


ROADMAP_JSON = (
    '{"nodes": ['
    '{"title": "Learn Agile", "detail": "d", "depends_on": []},'
    '{"title": "Apply to APM", "detail": "d", "depends_on": ["Learn Agile"]}'
    "]}"
)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(path=str(tmp_path / "chroma"), collection="testcol")


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def chats(db):
    return ConversationStore(db)


@pytest.fixture
def projects(db):
    return ProjectStore(db)


@pytest.fixture
def roadmaps(db):
    return RoadmapStore(db)


@pytest.fixture
def nodes(db):
    return RoadmapNodeStore(db)


@pytest.fixture
def profile(db):
    return ProfileStore(db)


@pytest.fixture
def project(projects):
    return projects.create("Career")


# --- generation and layout ---------------------------------------------


def test_generating_creates_a_roadmap_with_dependent_nodes(
    store, chats, projects, roadmaps, nodes, profile, project
):
    data = api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes, StubLLM(ROADMAP_JSON),
        profile, project.id, goal="Become a PM",
    )

    assert data["roadmap"]["goal"] == "Become a PM"
    titles = {n["title"] for n in data["nodes"]}
    assert titles == {"Learn Agile", "Apply to APM"}


def test_dependencies_resolve_to_real_node_ids(
    store, chats, projects, roadmaps, nodes, profile, project
):
    data = api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes, StubLLM(ROADMAP_JSON),
        profile, project.id, goal="Become a PM",
    )

    by_title = {n["title"]: n for n in data["nodes"]}
    dep_ids = by_title["Apply to APM"]["depends_on"]
    assert dep_ids == [by_title["Learn Agile"]["id"]]


def test_generating_without_a_goal_on_a_new_project_errors(
    store, chats, projects, roadmaps, nodes, profile, project
):
    data = api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes, StubLLM(ROADMAP_JSON),
        profile, project.id,
    )

    assert "error" in data


def test_regenerating_preserves_accepted_nodes(
    store, chats, projects, roadmaps, nodes, profile, project
):
    llm = StubLLM(ROADMAP_JSON)
    api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes, llm, profile, project.id,
        goal="Become a PM",
    )
    roadmap = roadmaps.for_project(project.id)
    accepted = nodes.for_roadmap(roadmap.id)[0]
    nodes.set_status(accepted.id, "accepted")
    nodes.set_note(accepted.id, "already doing this")

    api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes,
        StubLLM('{"nodes": [{"title": "New idea", "detail": "d"}]}'),
        profile, project.id,
    )

    survivor = nodes.get(accepted.id)
    assert survivor is not None
    assert survivor.status == "accepted"
    assert survivor.note == "already doing this"


def test_regenerating_removes_stale_proposed_nodes(
    store, chats, projects, roadmaps, nodes, profile, project
):
    api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes, StubLLM(ROADMAP_JSON),
        profile, project.id, goal="Goal",
    )
    roadmap = roadmaps.for_project(project.id)
    assert len(nodes.for_roadmap(roadmap.id)) == 2

    api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes,
        StubLLM('{"nodes": [{"title": "Only this", "detail": "d"}]}'),
        profile, project.id,
    )

    titles = {n.title for n in nodes.for_roadmap(roadmap.id)}
    assert titles == {"Only this"}


def test_decided_nodes_are_shown_to_the_model(
    store, chats, projects, roadmaps, nodes, profile, project
):
    api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes, StubLLM(ROADMAP_JSON),
        profile, project.id, goal="Goal",
    )
    roadmap = roadmaps.for_project(project.id)
    node = nodes.for_roadmap(roadmap.id)[0]
    nodes.set_status(node.id, "rejected")
    llm = StubLLM('{"nodes": [{"title": "X", "detail": "d"}]}')

    api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes, llm, profile, project.id
    )

    assert node.title in llm.last_user_prompt


def test_generation_failure_is_surfaced(
    store, chats, projects, roadmaps, nodes, profile, project
):
    data = api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes,
        StubLLM("", error=LLMError("rate limited")),
        profile, project.id, goal="Goal",
    )

    assert "error" in data


def test_missing_project_errors(store, chats, projects, roadmaps, nodes, profile):
    data = api.handle_generate_roadmap(
        store, chats, projects, roadmaps, nodes, StubLLM(ROADMAP_JSON),
        profile, "nope", goal="Goal",
    )

    assert "error" in data


def test_get_roadmap_on_a_project_with_none_yet_returns_empty_shell(
    roadmaps, nodes, project
):
    data = api.handle_get_roadmap(roadmaps, nodes, project.id)

    assert data["roadmap"] is None
    assert data["nodes"] == []


# --- spacing ------------------------------------------------------------

# A card is 220px wide; measured real cards run up to ~220px tall.
CARD_WIDTH = 220
MAX_OBSERVED_CARD_HEIGHT = 220


def test_column_width_leaves_a_gap_past_a_full_width_card():
    assert api.LAYOUT_COLUMN_WIDTH > CARD_WIDTH


def test_row_height_clears_the_tallest_observed_card():
    assert api.LAYOUT_ROW_HEIGHT > MAX_OBSERVED_CARD_HEIGHT


# --- tidy up --------------------------------------------------------------


def test_tidy_up_spaces_independent_nodes_into_the_same_column(nodes, roadmaps, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    a = nodes.add(roadmap.id, "A", x=5, y=5)
    b = nodes.add(roadmap.id, "B", x=8, y=8)

    api.handle_tidy_roadmap(nodes, roadmap.id)

    a2, b2 = nodes.get(a.id), nodes.get(b.id)
    assert a2.x == b2.x == 0
    assert {a2.y, b2.y} == {0, api.LAYOUT_ROW_HEIGHT}


def test_tidy_up_places_a_dependent_node_one_column_past_its_dependency(
    nodes, roadmaps, project
):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    base = nodes.add(roadmap.id, "Base", x=999, y=999)
    nodes.set_depends_on(base.id, [])
    dependent = nodes.add(roadmap.id, "Dependent", x=1, y=1)
    nodes.set_depends_on(dependent.id, [base.id])

    api.handle_tidy_roadmap(nodes, roadmap.id)

    base2 = nodes.get(base.id)
    dependent2 = nodes.get(dependent.id)
    assert dependent2.x == base2.x + api.LAYOUT_COLUMN_WIDTH


def test_tidy_up_returns_the_updated_nodes(nodes, roadmaps, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    nodes.add(roadmap.id, "A", x=999, y=999)

    data = api.handle_tidy_roadmap(nodes, roadmap.id)

    assert data["nodes"][0]["x"] == 0
    assert data["nodes"][0]["y"] == 0


def test_tidy_up_rows_accepted_work_before_proposed_and_done_before_rejected(
    nodes, roadmaps, project
):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    # Added in an order that would leave the wrong thing on top if row
    # placement just followed creation order.
    rejected = nodes.add(roadmap.id, "Rejected", status="rejected")
    done = nodes.add(roadmap.id, "Done", status="done")
    proposed = nodes.add(roadmap.id, "Proposed", status="proposed")
    accepted = nodes.add(roadmap.id, "Accepted", status="accepted")

    api.handle_tidy_roadmap(nodes, roadmap.id)

    by_status = {
        "accepted": nodes.get(accepted.id).y,
        "proposed": nodes.get(proposed.id).y,
        "done": nodes.get(done.id).y,
        "rejected": nodes.get(rejected.id).y,
    }
    assert by_status["accepted"] < by_status["proposed"]
    assert by_status["proposed"] < by_status["done"]
    assert by_status["done"] < by_status["rejected"]


# --- roadmap chat -----------------------------------------------------


def test_chat_reply_and_actions(roadmaps, nodes, profile, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    llm = StubLLM('{"reply": "Sure.", "actions": []}')

    data = api.handle_roadmap_chat(
        roadmaps, nodes, llm, profile, roadmap.id, "hi", []
    )

    assert data["reply"] == "Sure."
    assert data["actions"] == []


def test_chat_on_a_missing_roadmap_errors(roadmaps, nodes, profile):
    llm = StubLLM('{"reply": "Sure.", "actions": []}')

    data = api.handle_roadmap_chat(
        roadmaps, nodes, llm, profile, "nope", "hi", []
    )

    assert "error" in data


def test_chat_failure_is_surfaced(roadmaps, nodes, profile, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    llm = StubLLM("", error=LLMError("rate limited"))

    data = api.handle_roadmap_chat(
        roadmaps, nodes, llm, profile, roadmap.id, "hi", []
    )

    assert "error" in data


def test_chat_action_is_returned_as_a_dict(roadmaps, nodes, profile, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    llm = StubLLM(
        '{"reply": "I\'ll add that.", '
        '"actions": [{"type": "add_node", "title": "Learn SQL", "detail": "d"}]}'
    )

    data = api.handle_roadmap_chat(
        roadmaps, nodes, llm, profile, roadmap.id, "add a step for SQL", []
    )

    assert data["actions"][0]["type"] == "add_node"
    assert data["actions"][0]["title"] == "Learn SQL"


# --- node mutation --------------------------------------------------------


def test_updating_node_status(nodes, roadmaps, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    node = nodes.add(roadmap.id, "X")

    result = api.handle_update_node(nodes, node.id, {"status": "accepted"})

    assert result["status"] == "accepted"


def test_updating_node_position(nodes, roadmaps, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    node = nodes.add(roadmap.id, "X")

    result = api.handle_update_node(nodes, node.id, {"x": 100, "y": 200})

    assert result["x"] == 100 and result["y"] == 200


def test_updating_node_note(nodes, roadmaps, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    node = nodes.add(roadmap.id, "X")

    result = api.handle_update_node(nodes, node.id, {"note": "my thought"})

    assert result["note"] == "my thought"


def test_updating_a_missing_node_errors(nodes):
    assert "error" in api.handle_update_node(nodes, "nope", {"status": "accepted"})


def test_invalid_status_update_errors(nodes, roadmaps, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    node = nodes.add(roadmap.id, "X")

    assert "error" in api.handle_update_node(nodes, node.id, {"status": "bogus"})


def test_manually_added_node_is_accepted_by_default(nodes, roadmaps, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)

    result = api.handle_add_node(nodes, roadmap.id, {"title": "My own step"})

    assert result["status"] == "accepted"


def test_adding_a_node_with_a_blank_title_errors(nodes, roadmaps, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)

    assert "error" in api.handle_add_node(nodes, roadmap.id, {"title": "  "})


def test_deleting_a_node(nodes, roadmaps, project):
    roadmap = roadmaps.create("Goal", project_id=project.id)
    node = nodes.add(roadmap.id, "X")

    result = api.handle_delete_node(nodes, node.id)

    assert result["ok"] is True
    assert nodes.get(node.id) is None


def test_deleting_a_missing_node_errors(nodes):
    assert "error" in api.handle_delete_node(nodes, "nope")


# --- profile ----------------------------------------------------------


def test_get_profile_reports_empty_by_default(profile):
    data = api.handle_get_profile(profile)

    assert data["is_empty"] is True


def test_saving_profile_is_reflected_in_get(profile):
    api.handle_save_profile(profile, "CS student")

    assert api.handle_get_profile(profile)["content"] == "CS student"


def test_draft_profile_from_documents(store):
    store.add("Document: resume.pdf", "CS student content", [], kind="document")

    data = api.handle_draft_profile(store, StubLLM("Drafted: CS student."))

    assert data["draft"] == "Drafted: CS student."


def test_draft_profile_with_nothing_to_draft_from_errors(store):
    data = api.handle_draft_profile(store, StubLLM("x"))

    assert "error" in data
