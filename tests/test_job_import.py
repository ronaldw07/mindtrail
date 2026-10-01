"""Importing a job tracker sheet: header mapping, parsing, add-only sync."""

from datetime import date

import pytest

from mindtrail.ingest.job_import import (
    apply_plan,
    heuristic_mapping,
    parse_date,
    parse_stage,
    plan_import,
)
from mindtrail.llm import Completion
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize
from mindtrail.organize.jobs import JobStore
from mindtrail.web.jobs_api import handle_import_sheet

TODAY = date(2026, 10, 1)

SHEET = [
    ["Company", "Position", "Job Link", "Status", "Date Applied", "Notes"],
    ["IBM", "PM Intern", "https://ibm.com/j/1", "Interviewing", "9/20/2026", "extra time granted"],
    ["Google", "APM", "", "Not applied yet", "", ""],
    ["", "orphan row", "", "", "", ""],
    ["Stripe", "SWE Intern", "not a url", "Rejected after OA", "Sep 3", ""],
    ["IBM", "PM Intern", "", "", "", "duplicate row"],
]


class StubLLM:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def complete(self, system, user, max_tokens=900):
        self.calls += 1
        return Completion(text=self.text, tokens=1, model="stub")


class StubSheets:
    def __init__(self, rows):
        self.rows_value, self.links = rows, []

    def rows(self, link):
        self.links.append(link)
        return self.rows_value


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def jobs(db):
    return JobStore(db)


def test_keyword_mapping_puts_job_link_in_url_not_role():
    mapping = heuristic_mapping(SHEET[0])
    assert mapping == {"company": 0, "role": 1, "url": 2, "stage": 3,
                       "applied_at": 4, "notes": 5}


@pytest.mark.parametrize("text,stage", [
    ("Interviewing", "interview"), ("Phone screen", "interview"),
    ("Rejected after OA", "rejected"), ("OA sent", "oa"), ("HackerRank", "oa"),
    ("Offer!", "offer"), ("Not applied yet", "saved"), ("Applied", "applied"),
    ("Ghosted", "applied"), ("", "applied"), ("Job board", "applied"),
    ("Withdrew", "withdrawn"),
])
def test_parse_stage(text, stage):
    assert parse_stage(text) == stage


@pytest.mark.parametrize("text,iso", [
    ("2026-09-20", "2026-09-20"), ("9/20/2026", "2026-09-20"), ("9/20/26", "2026-09-20"),
    ("Sep 20, 2026", "2026-09-20"), ("September 20,2026", "2026-09-20"),
    ("Sep 3", "2026-09-03"), ("Dec 3", "2025-12-03"), ("soon", ""), ("", ""),
])
def test_parse_date(text, iso):
    assert parse_date(text, TODAY) == iso


def test_plan_creates_new_rows_skips_blank_and_duplicate_rows(jobs):
    plan = plan_import(SHEET, jobs, None, {}, TODAY)
    created = {(f["company"], f["stage"]) for f in plan.create}
    assert created == {("IBM", "interview"), ("Google", "saved"), ("Stripe", "rejected")}
    assert plan.skipped_rows == 2
    stripe = next(f for f in plan.create if f["company"] == "Stripe")
    assert stripe["url"] == "" and stripe["applied_at"] == "2026-09-03"


def test_dry_run_writes_nothing_and_apply_writes(jobs):
    plan = plan_import(SHEET, jobs, None, {}, TODAY)
    assert jobs.all() == []
    apply_plan(plan, jobs)
    assert len(jobs.all()) == 3
    assert {a.source for a in jobs.all()} == {"sheet"}


def test_resync_only_fills_empty_fields_and_never_overwrites(jobs):
    apply_plan(plan_import(SHEET, jobs, None, {}, TODAY), jobs)
    ibm = jobs.find("IBM", "PM Intern")
    jobs.update(ibm.id, {"stage": "offer", "notes": "edited in mindtrail", "location": ""})

    changed = [row[:] for row in SHEET]
    changed[0].append("Location")
    changed[1].append("Armonk")
    changed[1][5] = "sheet notes changed"
    changed[1][3] = "Rejected"
    plan = plan_import(changed, jobs, None, {}, TODAY)
    apply_plan(plan, jobs)

    ibm = jobs.get(ibm.id)
    assert (ibm.stage, ibm.notes, ibm.location) == ("offer", "edited in mindtrail", "Armonk")
    assert len(jobs.all()) == 3
    assert plan.unchanged == 2


def test_unusual_headers_ask_the_model_once_then_use_the_cache(jobs):
    rows = [["Org", "What", "Where I am"], ["Acme", "PM", "Applied"]]
    llm = StubLLM('{"company": "Org", "role": "What", "stage": "Where I am", "url": null}')
    cache = {}
    plan = plan_import(rows, jobs, llm, cache, TODAY)
    assert plan.create[0]["company"] == "Acme" and plan.create[0]["role"] == "PM"
    plan_import(rows, jobs, llm, cache, TODAY)
    assert llm.calls == 1


def test_model_mapping_ignores_headers_that_do_not_exist(jobs):
    rows = [["Org", "What"], ["Acme", "PM"]]
    llm = StubLLM('{"company": "Employer Name"}')
    with pytest.raises(ValueError, match="company column"):
        plan_import(rows, jobs, llm, {}, TODAY)


def test_handler_previews_then_applies_and_remembers_the_link(db, jobs):
    state, sheets = AppState(db), StubSheets(SHEET)
    link = "https://docs.google.com/spreadsheets/d/abc/edit"

    preview = handle_import_sheet(jobs, state, None, sheets, {"link": link, "dry_run": True})
    assert preview["applied"] is False and preview["summary"]["new"] == 3
    assert jobs.all() == [] and state.get("job_sheet_link") is None

    handle_import_sheet(jobs, state, None, sheets, {"link": link})
    assert len(jobs.all()) == 3 and state.get("job_sheet_link") == link

    resync = handle_import_sheet(jobs, state, None, sheets, {})
    assert resync["summary"]["new"] == 0 and sheets.links[-1] == link


def test_handler_without_any_link_explains(db, jobs):
    result = handle_import_sheet(jobs, AppState(db), None, StubSheets(SHEET), {})
    assert "link" in result["error"]
