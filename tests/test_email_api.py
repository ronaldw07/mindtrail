"""A to-do's job and source email, and opening that email in Gmail."""

from types import SimpleNamespace

from mindtrail.integrations.gmail import web_url
from mindtrail.integrations.google_api import GoogleFetchError
from mindtrail.web import email_api


class State(dict):
    def set(self, key, value):
        self[key] = value


class Jobs:
    def get(self, app_id):
        return {"a1": SimpleNamespace(company="GE Aerospace", role="AI Co-op", stage="rejected"),
                "a2": SimpleNamespace(company="IBM", role="PM Intern", stage="oa")}.get(app_id)


class Log:
    def get(self, message_id):
        return {"m1": {"message_id": "m1", "subject": "Interview with GE", "received_at": "2026-09-14T04:01:25"}}.get(message_id)


class Gmail:
    def __init__(self, fail=False):
        self.fail = fail

    def get(self, message_id):
        if self.fail:
            raise GoogleFetchError("network down")
        return SimpleNamespace(subject="Interview with GE", sender="Tsenta <x@y.com>",
                               received_at="2026-09-14", body="Dear Ronald, " * 200)

    def account(self):
        return "me@gmail.com"


def test_a_to_do_knows_its_job_and_email_and_flags_a_closed_job():
    data = {"tasks": [{"application_id": "a1", "source_message_id": "m1"},
                      {"application_id": "a2", "source_message_id": ""},
                      {"application_id": None, "source_message_id": "gone"}]}

    ge, ibm, loose = email_api.with_sources(data, Jobs(), Log(), State())["tasks"]

    assert ge["job"] == {"company": "GE Aerospace", "role": "AI Co-op", "stage": "rejected", "closed": True}
    assert ge["email"]["subject"] == "Interview with GE" and ge["email"]["url"].endswith("#all/m1")
    assert ibm["job"]["closed"] is False and "email" not in ibm
    assert "job" not in loose and "email" not in loose


def test_the_gmail_link_opens_in_the_connected_account_once_known():
    assert web_url("m1") == "https://mail.google.com/mail/u/0/#all/m1"
    assert web_url("m1", "me@gmail.com") == "https://mail.google.com/mail/?authuser=me%40gmail.com#all/m1"

    state = State()
    res = email_api.handle_email(Gmail(), Log(), state, "m1")

    assert state[email_api.ACCOUNT_KEY] == "me@gmail.com"
    assert "authuser=me%40gmail.com" in res["url"]
    assert len(res["preview"]) == email_api.PREVIEW_CHARS


def test_only_emails_mindtrail_read_can_be_previewed_and_failures_say_so():
    assert "isn't one" in email_api.handle_email(Gmail(), Log(), State(), "someone-elses")["error"]
    assert "network down" in email_api.handle_email(Gmail(fail=True), Log(), State(), "m1")["error"]
