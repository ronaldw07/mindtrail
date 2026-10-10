"""Recruiting handlers: results come back as dicts, bad input as {"error"}."""

from datetime import date

import pytest

from mindtrail.organize.db import initialize
from mindtrail.organize.interviews import InterviewStore
from mindtrail.organize.jobs import JobStore
from mindtrail.organize.offers import OfferStore
from mindtrail.organize.practice import PracticeStore
from mindtrail.organize.stories import StoryStore
from mindtrail.web import recruit_api

TODAY = date(2026, 10, 9)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


def test_rounds_add_update_delete(db):
    jobs, rounds = JobStore(db), InterviewStore(db)
    app = jobs.create("Notion")

    added = recruit_api.handle_add_round(rounds, app.id, {"date": "2026-10-12", "kind": "phone"})
    rid = added["round"]["id"]
    updated = recruit_api.handle_update_round(rounds, rid, {"questions": "Reverse a list"})
    deleted = recruit_api.handle_delete_round(rounds, rid)

    assert updated["round"]["questions"] == "Reverse a list" and deleted == {"ok": True}
    assert "error" in recruit_api.handle_add_round(rounds, "nope", {})
    assert "error" in recruit_api.handle_delete_round(rounds, rid)


def test_today_reminders_combine_interviews_and_due_problems(db):
    jobs, rounds, practice = JobStore(db), InterviewStore(db), PracticeStore(db)
    app = jobs.create("Notion")
    rounds.add(app.id, "2026-10-11", "technical")
    practice.add("Two Sum", solved_on="2026-10-01")

    out = recruit_api.handle_recruiting_today(rounds, practice, TODAY)

    assert out["interviews"][0]["company"] == "Notion" and out["interviews"][0]["days_away"] == 2
    assert out["practice_due"][0]["title"] == "Two Sum" and out["practice_due"][0]["due"] is True


def test_stories_come_back_with_theme_counts(db):
    stories = StoryStore(db)
    recruit_api.handle_create_story(stories, {"title": "A", "themes": "leadership", "situation": "x"})
    recruit_api.handle_create_story(stories, {"title": "B", "themes": "leadership,conflict"})

    out = recruit_api.handle_list_stories(stories)

    assert out["themes"][0] == {"theme": "leadership", "count": 2}
    assert "error" in recruit_api.handle_create_story(stories, {"title": ""})


def test_practice_list_flags_due_and_reviewing_advances_it(db):
    practice = PracticeStore(db)
    pid = recruit_api.handle_add_problem(practice, {"title": "Two Sum", "solved_on": "2026-10-01",
                                                    "topic": "arrays"})["problem"]["id"]

    before = recruit_api.handle_list_practice(practice, TODAY)
    reviewed = recruit_api.handle_review_problem(practice, pid, {"outcome": "solo"})

    assert before["due_count"] == 1 and before["coverage"][0]["topic"] == "arrays"
    assert reviewed["problem"]["reviews_done"] == 1
    assert "error" in recruit_api.handle_add_problem(practice, {"title": "x", "difficulty": "nope"})


def test_offers_list_names_the_company_and_offers_candidates(db):
    jobs, offers = JobStore(db), OfferStore(db)
    won = jobs.create("Stripe", stage="offer")
    jobs.create("Figma", stage="applied")
    recruit_api.handle_save_offer(offers, won.id, {"base": 120000, "bonus": 10000})

    out = recruit_api.handle_list_offers(offers, jobs)

    assert out["offers"][0]["company"] == "Stripe" and out["offers"][0]["first_year"] == 130000
    assert out["candidates"] == [{"id": won.id, "company": "Stripe", "role": ""}]
    assert "error" in recruit_api.handle_save_offer(offers, won.id, {"base": "lots"})
