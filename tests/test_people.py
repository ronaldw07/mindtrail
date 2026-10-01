"""People and nudges."""

from datetime import date, timedelta

import pytest

from mindtrail.organize.db import initialize
from mindtrail.organize.jobs import JobStore
from mindtrail.organize.people import PeopleStore, is_due
from mindtrail.web import admin_api

THU = date(2026, 10, 1)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def people(db):
    return PeopleStore(db)


def test_nudge_rules(people):
    today = date.today()
    never = people.create("Francis", nudge_every_days=14)
    recent = people.create("Carla", nudge_every_days=14,
                           last_contacted=(today - timedelta(days=6)).isoformat())
    overdue = people.create("Mom", nudge_every_days=7,
                            last_contacted=(today - timedelta(days=11)).isoformat())
    no_nudge = people.create("Acquaintance")
    assert [p.name for p in people.due(today)] == ["Mom"]
    assert not is_due(no_nudge, today) and not is_due(recent, today)


def test_someone_never_contacted_is_due_counting_from_when_they_were_added(people):
    today = date.today()
    never = people.create("Francis", nudge_every_days=14)
    assert not is_due(never, today)
    assert is_due(never, today + timedelta(days=14))


def test_validation(people):
    with pytest.raises(ValueError):
        people.create(" ")
    with pytest.raises(ValueError):
        people.create("x", nudge_every_days=400)
    with pytest.raises(ValueError):
        people.create("x", last_contacted="last week")


def test_talked_today_clears_the_nudge(people):
    p = people.create("Francis", nudge_every_days=14)
    admin_api.handle_update_person(people, p.id, {"talked_today": True}, THU)
    assert people.get(p.id).last_contacted == THU.isoformat()
    assert admin_api.nudges_today(people, THU) == []
    assert admin_api.nudges_today(people, THU + timedelta(days=14))[0]["days_since"] == 14


def test_list_shows_linked_company(db, people):
    app = JobStore(db).create("IBM")
    p = people.create("Recruiter Sam")
    people.update(p.id, {"application_id": app.id})
    data = admin_api.handle_list_people(people, JobStore(db), THU)
    assert data["people"][0]["company"] == "IBM"
    assert data["applications"][0]["company"] == "IBM"
