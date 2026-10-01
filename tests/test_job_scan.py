"""The Gmail job scan: classification, forward-only updates, dedupe,
catch-up windows, and failure handling. Gmail and the model are stubbed."""

import json
import threading
import time
from datetime import date, datetime

import pytest

from mindtrail.advice.job_scan import (
    FIRST_RUN_DAYS,
    LAST_SCAN_KEY,
    OVERLAP_SECONDS,
    JobScanner,
    ScanTimer,
    parse_classification,
)
from mindtrail.integrations.gmail import Message
from mindtrail.integrations.google_api import GoogleAuthError
from mindtrail.llm import Completion, LLMError
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize
from mindtrail.organize.email_log import EmailLog
from mindtrail.organize.jobs import JobStore
from mindtrail.organize.tasks import TaskStore

NOW = datetime(2026, 10, 1, 9, 0).timestamp()
TODAY = date(2026, 10, 1)


def msg(mid, subject):
    return Message(id=mid, sender="x@co.com", subject=subject,
                   received_at=f"2026-09-{10 + int(mid[-1]):02d}T10:00:00-07:00", body="...")


class FakeGmail:
    """Newest first, like the real API."""

    def __init__(self, messages, error=None):
        self.messages, self.error, self.queries = messages, error, []

    def search_ids(self, query, limit):
        self.queries.append(query)
        if self.error:
            raise self.error
        return [m.id for m in reversed(self.messages)][:limit]

    def get(self, mid):
        return next(m for m in self.messages if m.id == mid)


class ReplyBySubject:
    def __init__(self, replies, fail=()):
        self.replies, self.fail, self.calls = replies, set(fail), []

    def complete(self, system, user, max_tokens=900):
        subject = user.split("SUBJECT: ")[1].split("\n")[0]
        self.calls.append(subject)
        if subject in self.fail:
            raise LLMError("rate limited")
        return Completion(text=json.dumps(self.replies[subject]), tokens=1, model="stub")


def reply(company="", event="other", job=True, role="", todo="", due=""):
    return {"job_related": job, "company": company, "role": role, "event": event,
            "todo": todo, "todo_due": due}


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    initialize(path)
    return path


@pytest.fixture
def stores(db):
    return JobStore(db), TaskStore(db), EmailLog(db), AppState(db)


def scanner(stores, llm, gmail):
    jobs, tasks, log, state = stores
    return JobScanner(jobs, tasks, log, state, llm, gmail, clock=lambda: NOW)


def test_interview_email_moves_stage_and_adds_a_dated_todo(stores):
    jobs, tasks, log, _ = stores
    app = jobs.create("IBM", role="PM Intern")
    llm = ReplyBySubject({"Interview": reply("IBM", "interview", role="PM Intern",
                                             todo="Pick an interview slot", due="2026-10-05")})
    status = scanner(stores, llm, FakeGmail([msg("m1", "Interview")])).scan()

    assert status["ok"] and status["summary"]["stages_moved"] == 1
    assert jobs.get(app.id).stage == "interview"
    (task,) = tasks.for_application(app.id)
    assert (task.title, task.due_date) == ("Pick an interview slot", "2026-10-05")
    assert log.for_application(app.id)[0]["subject"] == "Interview"


def test_a_late_thanks_for_applying_never_moves_backward(stores):
    jobs = stores[0]
    app = jobs.create("IBM", stage="interview")
    llm = ReplyBySubject({"Thanks": reply("IBM", "applied")})
    scanner(stores, llm, FakeGmail([msg("m1", "Thanks")])).scan()
    assert jobs.get(app.id).stage == "interview"


def test_unknown_company_creates_an_application_flagged_for_review(stores):
    jobs = stores[0]
    llm = ReplyBySubject({"OA": reply("Ramp", "oa", todo="Finish the CodeSignal")})
    status = scanner(stores, llm, FakeGmail([msg("m1", "OA")])).scan()
    (app,) = jobs.all()
    assert (app.company, app.stage, app.needs_review, app.source) == ("Ramp", "oa", True, "email")
    assert app.applied_at == ""
    assert status["summary"]["new_applications"] == 1


def test_non_job_email_is_remembered_but_changes_nothing(stores):
    jobs, tasks, log, _ = stores
    llm = ReplyBySubject({"Newsletter": reply("Indeed", "other", job=False, todo="Read this")})
    scanner(stores, llm, FakeGmail([msg("m1", "Newsletter")])).scan()
    assert jobs.all() == [] and tasks.all() == []
    assert log.has("m1")


def test_each_email_is_classified_only_once_ever(stores):
    llm = ReplyBySubject({"A": reply("IBM", "applied")})
    gmail = FakeGmail([msg("m1", "A")])
    scanner(stores, llm, gmail).scan()
    scanner(stores, llm, gmail).scan()
    assert llm.calls == ["A"]


def test_emails_are_processed_oldest_first(stores):
    jobs = stores[0]
    llm = ReplyBySubject({"Applied": reply("Figma", "applied"),
                          "Interview": reply("Figma", "interview")})
    scanner(stores, llm, FakeGmail([msg("m1", "Applied"), msg("m2", "Interview")])).scan()
    assert llm.calls == ["Applied", "Interview"]
    assert jobs.all()[0].stage == "interview"


def test_failed_classification_is_retried_and_holds_the_window(stores):
    _, _, log, state = stores
    gmail = FakeGmail([msg("m1", "A")])
    first = scanner(stores, ReplyBySubject({}, fail={"A"}), gmail).scan()
    assert not first["ok"] and not log.has("m1")
    assert state.get(LAST_SCAN_KEY) is None

    second = scanner(stores, ReplyBySubject({"A": reply("IBM", "applied")}), gmail).scan()
    assert second["ok"] and log.has("m1")
    assert state.get(LAST_SCAN_KEY) == int(NOW)


def test_first_run_looks_back_sixty_days_then_resumes_from_last_scan(stores):
    gmail = FakeGmail([])
    scanner(stores, ReplyBySubject({}), gmail).scan()
    scanner(stores, ReplyBySubject({}), gmail).scan()
    assert gmail.queries[0].endswith(f"after:{int(NOW) - FIRST_RUN_DAYS * 86400}")
    assert gmail.queries[1].endswith(f"after:{int(NOW) - OVERLAP_SECONDS}")


def test_not_connected_is_a_status_not_an_exception(stores):
    gmail = FakeGmail([], error=GoogleAuthError("Google isn't connected"))
    status = scanner(stores, ReplyBySubject({}), gmail).scan()
    assert (status["ok"], status["connected"]) == (False, False)
    assert "connected" in stores[3].get("gmail_scan_status")["message"]


def test_model_output_outside_the_schema_is_dropped():
    c = parse_classification(json.dumps({
        "job_related": "yes", "company": "X" * 300, "event": "transfer_funds",
        "todo": "do it", "todo_due": "2031-01-01",
    }), TODAY)
    assert c.job_related is False  # only a real JSON true counts
    assert len(c.company) == 100 and c.event == "other" and c.todo_due == ""


def test_a_second_scan_while_one_runs_returns_immediately(stores):
    started, release = threading.Event(), threading.Event()

    class SlowGmail(FakeGmail):
        def search_ids(self, query, limit):
            started.set()
            release.wait(5)
            return []

    s = scanner(stores, ReplyBySubject({}), SlowGmail([]))
    worker = threading.Thread(target=s.scan)
    worker.start()
    started.wait(5)
    assert s.scan()["message"] == "a scan is already running"
    release.set()
    worker.join(5)


def test_timer_scans_once_immediately_on_start():
    calls = []

    class CountingScanner:
        def scan(self):
            calls.append(1)

    timer = ScanTimer(CountingScanner(), interval=3600)
    timer.start()
    deadline = time.time() + 5
    while not calls and time.time() < deadline:
        time.sleep(0.01)
    timer.stop()
    assert calls == [1]
