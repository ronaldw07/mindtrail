"""Life areas: seeding, validation, untagging on delete."""

import pytest

from mindtrail.organize.areas import DEFAULT_AREAS, AreaStore
from mindtrail.organize.db import initialize
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.tasks import TaskStore
from mindtrail.web import api, life_api


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def areas(db):
    return AreaStore(db)


def test_seeds_defaults_once_and_never_again_after_deleting(areas):
    areas.ensure_seeded()
    assert [a.name for a in areas.all()] == [name for name, _ in DEFAULT_AREAS]
    for a in areas.all():
        areas.delete(a.id)
    areas.ensure_seeded()
    assert areas.all() == []


def test_validates_name_and_color(areas):
    with pytest.raises(ValueError):
        areas.create(" ", "#112233")
    with pytest.raises(ValueError):
        areas.create("Family", "red")
    assert areas.create("Family", "#AABBCC").color == "#aabbcc"


def test_new_areas_sort_last(areas):
    first = areas.create("A", "#111111")
    second = areas.create("B", "#222222")
    assert second.sort == first.sort + 1


def test_delete_untags_projects_and_tasks(db, areas):
    health = areas.create("Health", "#3fb27f")
    project = ProjectStore(db).create("Marathon")
    areas.set_project_area(project.id, health.id)
    task = TaskStore(db).add("Run 5k", area_id=health.id)

    areas.delete(health.id)

    assert ProjectStore(db).get(project.id).area_id == ""
    assert TaskStore(db).get(task.id).area_id == ""


def test_project_area_must_exist_but_can_be_cleared(db, areas):
    project = ProjectStore(db).create("X")
    with pytest.raises(ValueError):
        areas.set_project_area(project.id, "missing")
    areas.set_project_area(project.id, "")
    assert areas.project_areas() == {}


def test_handlers_and_sidebar_report_areas(db, areas):
    career = life_api.handle_create_area(areas, {"name": "Career", "color": "#6d8cff"})["area"]
    project = ProjectStore(db).create("Recruiting")
    assert life_api.handle_set_project_area(areas, project.id, {"area_id": career["id"]}) == {"ok": True}
    assert life_api.handle_list_areas(areas)["project_areas"] == {project.id: career["id"]}
    sidebar = api.handle_sidebar(ProjectStore(db), __import__(
        "mindtrail.organize.conversations", fromlist=["ConversationStore"]).ConversationStore(db))
    assert sidebar["projects"][0]["area_id"] == career["id"]
    assert "error" in life_api.handle_update_area(areas, career["id"], {"name": "", "color": "#000000"})
