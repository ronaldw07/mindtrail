"""Interview rounds, story bank, practice log, offers - and their backup."""

from datetime import date

import pytest

from mindtrail.organize.db import connect, initialize
from mindtrail.organize.interviews import InterviewStore
from mindtrail.organize.jobs import JobStore
from mindtrail.organize.life_data import dump_tables, load_tables
from mindtrail.organize.offers import OfferStore
from mindtrail.organize.practice import REVIEW_GAPS, PracticeStore
from mindtrail.organize.stories import StoryStore, clean_themes

TODAY = date(2026, 10, 9)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def app(db):
    return JobStore(db).create("Notion", role="SWE Intern")


# --- interview rounds ---------------------------------------------------------


def test_rounds_belong_to_an_application_and_sort_by_date(db, app):
    rounds = InterviewStore(db)
    rounds.add(app.id, "2026-10-20", "onsite")
    rounds.add(app.id, "2026-10-12", "phone", interviewer="Sam")
    rounds.add(app.id)  # undated goes last

    got = rounds.for_application(app.id)

    assert [r.date for r in got] == ["2026-10-12", "2026-10-20", ""]


def test_a_round_needs_a_real_application_and_kind(db, app):
    rounds = InterviewStore(db)

    with pytest.raises(ValueError):
        rounds.add("nope")
    with pytest.raises(ValueError):
        rounds.add(app.id, kind="chat")


def test_updating_and_deleting_a_round(db, app):
    rounds = InterviewStore(db)
    r = rounds.add(app.id, "2026-10-12")

    updated = rounds.update(r.id, {"prep_notes": "Review graphs", "questions": "Two sum?", "kind": "technical"})
    rounds.delete(r.id)

    assert (updated.prep_notes, updated.kind) == ("Review graphs", "technical")
    assert rounds.for_application(app.id) == []
    with pytest.raises(ValueError):
        rounds.delete(r.id)


def test_upcoming_lists_the_next_week_with_days_away(db, app):
    rounds = InterviewStore(db)
    rounds.add(app.id, "2026-10-09", "phone")
    rounds.add(app.id, "2026-10-11", "technical")
    rounds.add(app.id, "2026-10-30", "onsite")
    rounds.add(app.id, "2026-10-01", "phone")

    up = rounds.upcoming(TODAY)

    assert [(u["company"], u["days_away"]) for u in up] == [("Notion", 0), ("Notion", 2)]


def test_deleting_an_application_removes_its_rounds(db, app):
    rounds = InterviewStore(db)
    rounds.add(app.id, "2026-10-12")

    JobStore(db).delete(app.id)

    assert rounds.upcoming(TODAY) == []


# --- stories ------------------------------------------------------------------


def test_themes_are_cleaned_and_deduplicated():
    assert clean_themes(" Leadership, conflict ,leadership,, FAILURE ") == "leadership,conflict,failure"
    assert clean_themes(["Teamwork", "teamwork"]) == "teamwork"


def test_a_story_round_trips_and_lists_newest_edit_first(db):
    stories = StoryStore(db)
    a = stories.create("Led the migration", situation="Legacy app", themes="leadership")
    b = stories.create("Missed a deadline", themes="failure,ownership")
    stories.update(a.id, {"result": "Shipped a week early"})

    assert [s.title for s in stories.all()] == ["Led the migration", "Missed a deadline"]
    assert stories.get(a.id).result == "Shipped a week early"
    assert b.theme_list == ["failure", "ownership"]


def test_theme_counts_most_used_first(db):
    stories = StoryStore(db)
    stories.create("A", themes="leadership,conflict")
    stories.create("B", themes="leadership")

    assert stories.themes() == [("leadership", 2), ("conflict", 1)]


def test_a_story_needs_a_title(db):
    stories = StoryStore(db)
    with pytest.raises(ValueError):
        stories.create("  ")
    s = stories.create("Ok")
    with pytest.raises(ValueError):
        stories.update(s.id, {"title": ""})


# --- practice -----------------------------------------------------------------


def test_a_problem_comes_back_after_one_three_seven_then_twenty_one_days(db):
    practice = PracticeStore(db)
    p = practice.add("Two Sum", solved_on="2026-10-01", topic="Arrays")
    seen = [p.next_review()]
    day = date(2026, 10, 1)
    for _ in REVIEW_GAPS:
        p = practice.mark_reviewed(p.id, today=day)
        seen.append(p.next_review())
        day = date.fromisoformat(p.next_review()) if p.next_review() else day

    assert seen == ["2026-10-02", "2026-10-04", "2026-10-11", "2026-11-01", ""]


def test_due_lists_what_is_ready_longest_waiting_first(db):
    practice = PracticeStore(db)
    practice.add("Old", solved_on="2026-09-01")
    practice.add("Yesterday", solved_on="2026-10-08")
    practice.add("Today", solved_on="2026-10-09")

    assert [p.title for p in practice.due(TODAY)] == ["Old", "Yesterday"]


def test_a_finished_problem_is_never_due_again(db):
    practice = PracticeStore(db)
    p = practice.add("Done", solved_on="2026-01-01")
    for _ in REVIEW_GAPS:
        p = practice.mark_reviewed(p.id, today=TODAY)

    assert practice.due(date(2027, 1, 1)) == []


def test_problem_input_is_validated(db):
    practice = PracticeStore(db)
    for bad in ({"title": " "}, {"title": "x", "difficulty": "brutal"}, {"title": "x", "outcome": "?"},
                {"title": "x", "url": "javascript:alert(1)"}):
        with pytest.raises(ValueError):
            practice.add(**bad)


def test_coverage_counts_per_topic_and_solo_solves(db):
    practice = PracticeStore(db)
    practice.add("a", topic="Graphs", outcome="solo")
    practice.add("b", topic="graphs", outcome="help")
    practice.add("c", topic="dp", outcome="stuck")

    assert practice.coverage() == [
        {"topic": "graphs", "total": 2, "solo": 1}, {"topic": "dp", "total": 1, "solo": 0}]


# --- offers -------------------------------------------------------------------


def test_first_year_adds_up_everything_paid_in_year_one(db, app):
    offers = OfferStore(db)

    o = offers.save(app.id, {"base": "120,000", "bonus": 10000, "equity_per_year": "$20000", "signing": 5000})

    assert o.first_year == 155000


def test_saving_again_changes_only_the_fields_given(db, app):
    offers = OfferStore(db)
    offers.save(app.id, {"base": 100000, "location": "Remote"})

    o = offers.save(app.id, {"bonus": 5000})

    assert (o.base, o.bonus, o.location) == (100000, 5000, "Remote")


def test_offers_list_highest_first_and_reject_bad_amounts(db, app):
    other = JobStore(db).create("Stripe")
    offers = OfferStore(db)
    offers.save(app.id, {"base": 100000})
    offers.save(other.id, {"base": 150000})

    assert [o.application_id for o in offers.all()] == [other.id, app.id]
    with pytest.raises(ValueError):
        offers.save(app.id, {"base": "lots"})
    with pytest.raises(ValueError):
        offers.save(app.id, {"base": -5})
    with pytest.raises(ValueError):
        offers.save("nope", {"base": 1})


# --- backup coverage ----------------------------------------------------------


def test_the_new_tables_survive_a_backup_round_trip(db, app, tmp_path):
    InterviewStore(db).add(app.id, "2026-10-12", prep_notes="graphs")
    StoryStore(db).create("Story", themes="leadership")
    PracticeStore(db).add("Two Sum", solved_on="2026-10-01")
    OfferStore(db).save(app.id, {"base": 100000})
    dumped = dump_tables(db)

    other = str(tmp_path / "other.db")
    initialize(other)
    created, skipped, failed, warnings = load_tables(other, dumped, overwrite=False)

    assert failed == 0, warnings
    with connect(other) as conn:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("interview_rounds", "stories", "practice", "offers")}
    assert counts == {"interview_rounds": 1, "stories": 1, "practice": 1, "offers": 1}
