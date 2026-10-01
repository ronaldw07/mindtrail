"""Pasting a job link: field extraction and every degraded path."""

from datetime import date

import pytest

from mindtrail.ingest.fetch import FetchError
from mindtrail.ingest.job_posting import add_from_link, company_from_url
from mindtrail.llm import Completion, LLMError
from mindtrail.organize.db import initialize
from mindtrail.organize.jobs import JobStore

TODAY = date(2026, 10, 1)
PAGE = "<html><head><title>PM Intern - Acme</title></head><body>Apply by Oct 15</body></html>"


class StubLLM:
    def __init__(self, text="", error=None):
        self.text, self.error, self.prompts = text, error, []

    def complete(self, system, user, max_tokens=900):
        self.prompts.append(user)
        if self.error:
            raise self.error
        return Completion(text=self.text, tokens=1, model="stub")


@pytest.fixture
def jobs(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return JobStore(path)


@pytest.mark.parametrize("url,company", [
    ("https://boards.greenhouse.io/stripe/jobs/123", "Stripe"),
    ("https://jobs.lever.co/jane-street/abc", "Jane Street"),
    ("https://jobs.ashbyhq.com/openai/xyz", "Openai"),
    ("https://ibm.wd1.myworkdayjobs.com/en-US/External/job/1", "Ibm"),
    ("https://careers.google.com/jobs/results/1", "Google"),
    ("https://www.linkedin.com/jobs/view/123", ""),
])
def test_company_from_url(url, company):
    assert company_from_url(url) == company


def test_model_fields_fill_the_application(jobs):
    llm = StubLLM('```json\n{"company": "Acme", "role": "PM Intern", '
                  '"location": "Remote", "deadline": "2026-10-15"}\n```')
    app, warning = add_from_link(jobs, llm, "https://acme.com/jobs/1",
                                 fetch=lambda u: PAGE, today=TODAY)
    assert warning is None
    assert (app.company, app.role, app.location, app.deadline) == (
        "Acme", "PM Intern", "Remote", "2026-10-15")
    assert (app.stage, app.applied_at, app.source) == ("applied", "2026-10-01", "link")
    assert "TODAY: 2026-10-01" in llm.prompts[0]


def test_a_made_up_deadline_and_overlong_fields_are_cleaned(jobs):
    llm = StubLLM('{"company": "' + "A" * 500 + '", "role": "PM", "deadline": "soon"}')
    app, _ = add_from_link(jobs, llm, "https://acme.com/j", fetch=lambda u: PAGE, today=TODAY)
    assert len(app.company) == 100
    assert app.deadline == ""


def test_login_wall_still_saves_with_company_from_url(jobs):
    def blocked(url):
        raise FetchError("403")
    llm = StubLLM()
    app, warning = add_from_link(jobs, llm, "https://jobs.lever.co/ramp/1",
                                 fetch=blocked, today=TODAY)
    assert app.company == "Ramp"
    assert "fill in" in warning
    assert llm.prompts == []


def test_model_failure_still_saves(jobs):
    app, warning = add_from_link(jobs, StubLLM(error=LLMError("down")),
                                 "https://boards.greenhouse.io/figma/jobs/9",
                                 fetch=lambda u: PAGE, today=TODAY)
    assert app.company == "Figma"
    assert warning


def test_unknown_company_falls_back_to_host(jobs):
    def blocked(url):
        raise FetchError("403")
    app, warning = add_from_link(jobs, None, "https://www.linkedin.com/jobs/view/1",
                                 fetch=blocked, today=TODAY)
    assert app.company == "www.linkedin.com"
    assert warning


def test_same_link_twice_returns_the_existing_application(jobs):
    llm = StubLLM('{"company": "Acme"}')
    first, _ = add_from_link(jobs, llm, "https://acme.com/j", fetch=lambda u: PAGE, today=TODAY)
    second, warning = add_from_link(jobs, llm, "https://acme.com/j",
                                    fetch=lambda u: PAGE, today=TODAY)
    assert second.id == first.id
    assert warning == "already tracked"
    assert len(jobs.all()) == 1


def test_saved_stage_has_no_applied_date(jobs):
    app, _ = add_from_link(jobs, StubLLM('{"company": "Acme"}'), "https://acme.com/j",
                           stage="saved", fetch=lambda u: PAGE, today=TODAY)
    assert app.stage == "saved" and app.applied_at == ""


def test_rejects_non_http_links(jobs):
    with pytest.raises(ValueError):
        add_from_link(jobs, None, "file:///etc/passwd", fetch=lambda u: PAGE)
