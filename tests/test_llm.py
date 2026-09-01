"""Retry and backoff tests.

The free tier's rate limit is the reason this project retries at all, so
the loop is exercised directly: attempt counts, the backoff sequence, and
which exception types are retried versus raised immediately.
"""

import httpx
import pytest
from groq import RateLimitError

from mindtrail import config
from mindtrail.llm import LLMClient, LLMError


def a_rate_limit_error() -> RateLimitError:
    """RateLimitError requires a real httpx response to construct."""
    request = httpx.Request("POST", "http://groq.test/chat")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


class StubCompletions:
    """Raises the queued errors in order, then returns a success payload."""

    def __init__(self, errors=(), tokens=99):
        self._errors = list(errors)
        self._tokens = tokens
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)

        message = type("Message", (), {"content": "the answer"})()
        choice = type("Choice", (), {"message": message})()
        usage = type("Usage", (), {"total_tokens": self._tokens})()
        return type("Response", (), {"choices": [choice], "usage": usage})()


@pytest.fixture
def client(monkeypatch):
    """An LLMClient whose transport and sleeping are both stubbed."""
    slept: list[float] = []
    monkeypatch.setattr("mindtrail.llm.time.sleep", slept.append)

    def build(errors=()):
        instance = LLMClient(api_key="test-key")
        stub = StubCompletions(errors)
        instance._client = type(
            "Groq", (), {"chat": type("Chat", (), {"completions": stub})()}
        )()
        return instance, stub, slept

    return build


def test_successful_call_returns_a_completion(client):
    llm, stub, slept = client()

    result = llm.complete("system", "user")

    assert result.text == "the answer"
    assert result.tokens == 99
    assert stub.calls == 1
    assert slept == []


def test_call_recovers_after_transient_rate_limits(client):
    llm, stub, slept = client(errors=[a_rate_limit_error(), a_rate_limit_error()])

    result = llm.complete("system", "user")

    assert result.text == "the answer"
    assert stub.calls == 3


def test_backoff_doubles_between_attempts(client):
    llm, _, slept = client(errors=[a_rate_limit_error(), a_rate_limit_error()])

    llm.complete("system", "user")

    first = config.INITIAL_BACKOFF_SECONDS
    assert slept == [first, first * 2]


def test_exhausted_retries_raise_llm_error(client):
    always_limited = [a_rate_limit_error() for _ in range(config.MAX_RETRIES)]
    llm, stub, _ = client(errors=always_limited)

    with pytest.raises(LLMError, match="rate limited"):
        llm.complete("system", "user")

    assert stub.calls == config.MAX_RETRIES


def test_no_sleep_after_the_final_attempt(client):
    always_limited = [a_rate_limit_error() for _ in range(config.MAX_RETRIES)]
    llm, _, slept = client(errors=always_limited)

    with pytest.raises(LLMError):
        llm.complete("system", "user")

    # Sleeping after the last attempt would waste a full backoff interval
    # before failing anyway.
    assert len(slept) == config.MAX_RETRIES - 1


def test_other_errors_are_not_retried(client):
    llm, stub, slept = client(errors=[ValueError("malformed request")])

    with pytest.raises(LLMError, match="completion failed"):
        llm.complete("system", "user")

    assert stub.calls == 1
    assert slept == []


def test_missing_api_key_is_rejected_at_construction():
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        LLMClient(api_key="")


def test_temperature_is_passed_through(client, monkeypatch):
    llm, stub, _ = client()
    seen = {}
    original = stub.create

    def capture(**kwargs):
        seen.update(kwargs)
        return original(**kwargs)

    stub.create = capture
    llm._temperature = 0.0

    llm.complete("system", "user")

    assert seen["temperature"] == 0.0
