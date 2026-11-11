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


# --- out for the day: move on instead of waiting ----------------------------


def a_daily_limit_error(retry="59m52.9s") -> RateLimitError:
    request = httpx.Request("POST", "http://groq.test/chat")
    response = httpx.Response(status_code=429, request=request)
    message = (f"Rate limit reached for model `openai/gpt-oss-120b` on tokens per day (TPD): "
               f"Limit 200000, Used 199482. Please try again in {retry}.")
    return RateLimitError(message, response=response, body=None)


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    monkeypatch.setattr("mindtrail.llm._spent_until", {})
    monkeypatch.setattr(config, "CEREBRAS_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")


def test_a_spent_day_moves_to_the_smaller_model_without_waiting(client, monkeypatch):
    llm, stub, slept = client(errors=[a_daily_limit_error()])
    models = []
    original = stub.create
    stub.create = lambda **kw: (models.append(kw["model"]), original(**kw))[1]

    first = llm.complete("system", "user")
    second = llm.complete("system", "user")

    assert (first.model, second.model) == (config.FALLBACK_MODEL, config.FALLBACK_MODEL)
    assert models == [config.SYNTHESIS_MODEL, config.FALLBACK_MODEL, config.FALLBACK_MODEL]
    assert slept == []   # the spent model isn't retried, or tried again until it resets


def test_when_every_model_is_spent_it_says_so_plainly(client):
    llm, _, slept = client(errors=[a_daily_limit_error("59m52.9s"), a_daily_limit_error("1h2m0s")])

    with pytest.raises(LLMError, match="Out of free AI for now.*about 60 min.*GEMINI_API_KEY"):
        llm.complete("system", "user")

    assert slept == []


def test_a_gemini_key_is_the_last_backup(client, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "g-key")
    llm, _, _ = client(errors=[a_daily_limit_error(), a_daily_limit_error()])
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(url=url, auth=headers["Authorization"], model=json["model"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "from gemini"}}],
                                         "usage": {"total_tokens": 7}})

    monkeypatch.setattr("mindtrail.llm.httpx.post", post)

    result = llm.complete("system", "user")

    assert (result.text, result.model, result.tokens) == ("from gemini", config.GEMINI_MODEL, 7)
    assert sent["url"].endswith("/v1beta/openai/chat/completions") and sent["auth"] == "Bearer g-key"


def test_an_overloaded_backup_is_skipped_and_errors_never_show_a_key(client, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "secret-gemini-key")
    llm, _, _ = client(errors=[a_daily_limit_error(), a_daily_limit_error()])
    monkeypatch.setattr("mindtrail.llm.httpx.post", lambda url, headers, json, timeout:
                        httpx.Response(503, text="overloaded"))

    with pytest.raises(LLMError, match="Out of free AI"):
        llm.complete("system", "user")

    monkeypatch.setattr("mindtrail.llm.httpx.post", lambda url, headers, json, timeout:
                        httpx.Response(400, text="bad key secret-gemini-key"))
    monkeypatch.setattr("mindtrail.llm._spent_until", {})
    llm2, _, _ = client(errors=[a_daily_limit_error(), a_daily_limit_error()])
    with pytest.raises(LLMError) as err:
        llm2.complete("system", "user")

    assert "secret-gemini-key" not in str(err.value) and "[key hidden]" in str(err.value)


def _groq_replying(llm, content):
    def create(**kwargs):
        message = type("Message", (), {"content": content})()
        usage = type("Usage", (), {"total_tokens": 200})()
        return type("Response", (), {"choices": [type("Choice", (), {"message": message})()], "usage": usage})()
    llm._client = type("Groq", (), {"chat": type("Chat", (), {"completions": type("C", (), {"create": staticmethod(create)})()})()})()


def test_an_empty_reply_moves_on_to_gemini_with_its_thinking_kept_short(client, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "g-key")
    llm, _, _ = client()
    _groq_replying(llm, "")
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(json)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}],
                                         "usage": {"total_tokens": 9}})

    monkeypatch.setattr("mindtrail.llm.httpx.post", post)

    result = llm.complete("system", "user", max_tokens=200)

    assert (result.text, result.model) == ('{"ok": true}', config.GEMINI_MODEL)
    assert sent["reasoning_effort"] == "low", "or a 200-token reply is all thinking and no answer"


def test_when_every_model_answers_with_nothing_it_fails_instead_of_returning_blank(client, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "g-key")
    llm, _, _ = client()
    _groq_replying(llm, "   ")
    monkeypatch.setattr("mindtrail.llm.httpx.post", lambda url, headers, json, timeout: httpx.Response(
        200, json={"choices": [{"message": {"content": None}}], "usage": {"total_tokens": 200}}))

    with pytest.raises(LLMError, match="ran out of room"):
        llm.complete("system", "user")
