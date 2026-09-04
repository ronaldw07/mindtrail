"""Template data integrity and the apply-template handler."""

import pytest

from mindtrail.organize.db import initialize
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmap_templates import TEMPLATES
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.web import api


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


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
def project(projects):
    return projects.create("Career")


# --- template data integrity --------------------------------------------


def test_template_ids_are_unique():
    ids = [t.id for t in TEMPLATES]
    assert len(ids) == len(set(ids))


def test_every_template_has_at_least_five_steps():
    for t in TEMPLATES:
        assert len(t.steps) >= 5, f"{t.id} has only {len(t.steps)} steps"


def test_every_step_has_a_title_and_detail():
    for t in TEMPLATES:
        for s in t.steps:
            assert s.title.strip(), f"{t.id} has a step with a blank title"
            assert s.detail.strip(), f"{t.id}: '{s.title}' has a blank detail"


def test_titles_are_unique_within_a_template():
    for t in TEMPLATES:
        titles = [s.title for s in t.steps]
        assert len(titles) == len(set(titles)), f"{t.id} has duplicate titles"


def test_depends_on_resolves_within_the_same_template():
    for t in TEMPLATES:
        titles = {s.title for s in t.steps}
        for s in t.steps:
            for dep in s.depends_on:
                assert dep in titles, (
                    f"{t.id}: '{s.title}' depends on '{dep}', "
                    f"which is not a step in this template"
                )


def test_no_dependency_cycles():
    for t in TEMPLATES:
        by_title = {s.title: s for s in t.steps}

        def has_cycle(title: str, path: frozenset[str]) -> bool:
            if title in path:
                return True
            step = by_title.get(title)
            if step is None:
                return False
            return any(has_cycle(d, path | {title}) for d in step.depends_on)

        for s in t.steps:
            assert not has_cycle(s.title, frozenset()), (
                f"{t.id}: cycle involving '{s.title}'"
            )


# --- handle_list_templates -----------------------------------------------


def test_list_templates_returns_one_entry_per_template():
    data = api.handle_list_templates()

    assert len(data["templates"]) == len(TEMPLATES)


def test_list_templates_reports_correct_step_count():
    data = api.handle_list_templates()

    by_id = {t["id"]: t for t in data["templates"]}
    for template in TEMPLATES:
        assert by_id[template.id]["step_count"] == len(template.steps)
        assert by_id[template.id]["name"] == template.name
        assert by_id[template.id]["description"] == template.description


# --- handle_apply_template ------------------------------------------------


TEMPLATE_ID = TEMPLATES[0].id
TEMPLATE = TEMPLATES[0]


def test_applying_to_a_project_with_no_roadmap_creates_one_with_the_goal(
    roadmaps, nodes, projects, project
):
    data = api.handle_apply_template(
        roadmaps, nodes, projects, project.id, TEMPLATE_ID, goal="My goal"
    )

    assert data["roadmap"]["goal"] == "My goal"


def test_applying_without_a_goal_falls_back_to_the_template_name(
    roadmaps, nodes, projects, project
):
    data = api.handle_apply_template(roadmaps, nodes, projects, project.id, TEMPLATE_ID)

    assert data["roadmap"]["goal"] == TEMPLATE.name


def test_every_created_node_is_proposed(roadmaps, nodes, projects, project):
    data = api.handle_apply_template(roadmaps, nodes, projects, project.id, TEMPLATE_ID)

    assert len(data["nodes"]) == len(TEMPLATE.steps)
    assert all(n["status"] == "proposed" for n in data["nodes"])


def test_depends_on_is_resolved_to_real_node_ids_matching_the_template_graph(
    roadmaps, nodes, projects, project
):
    data = api.handle_apply_template(roadmaps, nodes, projects, project.id, TEMPLATE_ID)

    by_title = {n["title"]: n for n in data["nodes"]}
    for step in TEMPLATE.steps:
        expected_ids = {by_title[d]["id"] for d in step.depends_on}
        assert set(by_title[step.title]["depends_on"]) == expected_ids


def test_applying_twice_appends_rather_than_replaces(roadmaps, nodes, projects, project):
    api.handle_apply_template(roadmaps, nodes, projects, project.id, TEMPLATE_ID)
    data = api.handle_apply_template(roadmaps, nodes, projects, project.id, TEMPLATE_ID)

    assert len(data["nodes"]) == len(TEMPLATE.steps) * 2


def test_applying_to_a_roadmap_with_existing_nodes_leaves_them_untouched(
    roadmaps, nodes, projects, project
):
    roadmap = roadmaps.create("Existing goal", project_id=project.id)
    pre_existing = nodes.add(roadmap.id, "Hand written step", status="accepted")

    data = api.handle_apply_template(roadmaps, nodes, projects, project.id, TEMPLATE_ID)

    survivor = next(n for n in data["nodes"] if n["id"] == pre_existing.id)
    assert survivor["status"] == "accepted"
    assert survivor["title"] == "Hand written step"
    # goal from the pre-existing roadmap is untouched, not overwritten
    assert data["roadmap"]["goal"] == "Existing goal"
    assert len(data["nodes"]) == len(TEMPLATE.steps) + 1


def test_unknown_project_errors(roadmaps, nodes, projects):
    data = api.handle_apply_template(roadmaps, nodes, projects, "nope", TEMPLATE_ID)

    assert "error" in data


def test_unknown_template_errors(roadmaps, nodes, projects, project):
    data = api.handle_apply_template(roadmaps, nodes, projects, project.id, "nope")

    assert "error" in data
