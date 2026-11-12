"""Groq client with retry handling, and backups for when a day runs out.

The free tier allows roughly 30 requests and 12K tokens per minute, so a
long eval sweep will hit 429 partway through. Retrying with exponential
backoff is load-bearing here, not defensive padding.

A per-minute limit clears in seconds, so it is retried. A per-day limit
(tokens or requests per day) won't, so retrying only makes you wait: the
call moves straight on to the next model instead - Groq's smaller model,
then Cerebras and Gemini if their keys are set - and skips the spent one
until it resets.
"""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass

import httpx
from groq import Groq, RateLimitError

from mindtrail import config


class LLMError(RuntimeError):
    """Raised when a completion could not be obtained."""


class _OutForToday(Exception):
    """A model's daily allowance is spent; `seconds` until it resets."""

    def __init__(self, message: str, seconds: float):
        super().__init__(message)
        self.seconds = seconds


# Providers other than Groq, by name: (base URL, key). Both accept the
# OpenAI chat-completions request as is.
_OPENAI_STYLE = {
    "cerebras": ("https://api.cerebras.ai/v1", lambda: config.CEREBRAS_API_KEY),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", lambda: config.GEMINI_API_KEY),
}
# Gemini counts its thinking against max_tokens: at its default effort a
# short reply (an email's JSON) is cut off before any answer is written.
_REASONING_EFFORT = {"gemini": "low"}
DAILY_LIMIT = re.compile(r"per day|\bTPD\b|\bRPD\b|daily", re.IGNORECASE)
RESET_IN = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.IGNORECASE)
DEFAULT_RESET_SECONDS = 15 * 60
HTTP_TIMEOUT_SECONDS = 120
# (provider, model) -> time.monotonic() when it can be tried again.
_spent_until: dict[tuple[str, str], float] = {}


def _reset_seconds(message: str) -> float:
    m = RESET_IN.search(message)
    if not m or not any(m.groups()):
        return DEFAULT_RESET_SECONDS
    h, mins, secs = (float(g or 0) for g in m.groups())
    return h * 3600 + mins * 60 + secs


BUSY_RETRY_SECONDS = 60   # a backup that says it's overloaded is skipped this long


def _scrub(text: str) -> str:
    """Errors are shown in the browser; make sure no API key can ride along."""
    for key in (config.GROQ_API_KEY, config.CEREBRAS_API_KEY, config.GEMINI_API_KEY):
        if key:
            text = text.replace(key, "[key hidden]")
    return text


def _is_spent(route: tuple[str, str]) -> bool:
    return _spent_until.get(route, 0) > time.monotonic()


@dataclass(frozen=True)
class Completion:
    text: str
    tokens: int
    model: str


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = config.DEFAULT_TEMPERATURE,
    ):
        key = api_key if api_key is not None else config.GROQ_API_KEY
        if not key:
            raise LLMError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self._client = Groq(api_key=key)
        self._model = model or config.SYNTHESIS_MODEL
        self._temperature = temperature

    def complete(self, system: str, user: str, max_tokens: int = 900) -> Completion:
        """Single-turn completion, retrying through rate limits and moving
        on to the next model when one is out for the day or answers with
        nothing."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        waits, empty = [], False
        for provider, model in self._routes():
            if _is_spent((provider, model)):
                waits.append(_spent_until[(provider, model)] - time.monotonic())
                continue
            try:
                if provider == "groq":
                    response = self._with_retries(messages, max_tokens, model)
                    reply = Completion(text=response.choices[0].message.content or "",
                                       tokens=response.usage.total_tokens, model=model)
                else:
                    reply = self._openai_style(provider, model, messages, max_tokens)
            except _OutForToday as exc:
                _spent_until[(provider, model)] = time.monotonic() + exc.seconds
                waits.append(exc.seconds)
                continue
            if reply.text.strip():
                return reply
            empty = True   # it spent the whole budget thinking: try the next one
        if empty:
            raise LLMError("The AI ran out of room before answering. Try again.")
        minutes = max(1, round(min(waits or [DEFAULT_RESET_SECONDS]) / 60))
        raise LLMError(
            f"Out of free AI for now: every model has hit its daily limit. More frees up in about "
            f"{minutes} min. Add a CEREBRAS_API_KEY or GEMINI_API_KEY to .env to keep going."
        )

    def _routes(self) -> list[tuple[str, str]]:
        routes = [("groq", self._model)]
        if config.FALLBACK_MODEL != self._model:
            routes.append(("groq", config.FALLBACK_MODEL))
        if config.CEREBRAS_API_KEY:
            routes.append(("cerebras", config.CEREBRAS_MODEL))
        if config.GEMINI_API_KEY:
            routes.append(("gemini", config.GEMINI_MODEL))
        return routes

    def _openai_style(self, provider: str, model: str, messages: list[dict], max_tokens: int) -> Completion:
        base, key = _OPENAI_STYLE[provider]
        try:
            response = httpx.post(
                base + "/chat/completions", timeout=HTTP_TIMEOUT_SECONDS,
                headers={"Authorization": f"Bearer {key()}"},
                json={"model": model, "messages": messages, "max_tokens": max_tokens,
                      "temperature": self._temperature,
                      **({"reasoning_effort": _REASONING_EFFORT[provider]} if provider in _REASONING_EFFORT else {})},
            )
        except httpx.HTTPError as exc:
            raise LLMError(_scrub(f"{provider} request failed: {exc}")) from exc
        if response.status_code == 429:
            # A backup's limit is treated as spent until it says otherwise.
            raise _OutForToday(response.text, _reset_seconds(response.text))
        if response.status_code == 503:   # overloaded for now: try the next one
            raise _OutForToday(response.text, BUSY_RETRY_SECONDS)
        if response.status_code != 200:
            raise LLMError(_scrub(f"{provider} completion failed ({response.status_code}): {response.text[:300]}"))
        data = response.json()
        return Completion(text=data["choices"][0]["message"].get("content") or "",
                          tokens=(data.get("usage") or {}).get("total_tokens", 0), model=model)

    def describe_image(self, prompt: str, image: bytes, mime: str, max_tokens: int = 1500) -> str:
        """What's in an image, as text. Only Gemini here can see, so this
        needs a GEMINI_API_KEY."""
        if not config.GEMINI_API_KEY:
            raise LLMError("Reading screenshots needs a GEMINI_API_KEY in .env.")
        url = f"data:{mime};base64," + base64.b64encode(image).decode()
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt},
                                                 {"type": "image_url", "image_url": {"url": url}}]}]
        try:
            text = self._openai_style("gemini", config.GEMINI_MODEL, messages, max_tokens).text
        except _OutForToday as exc:
            raise LLMError("The screenshot reader is busy right now. Try again in a minute.") from exc
        if not text.strip():
            raise LLMError("Couldn't make out anything in that image.")
        return text

    def transcribe(self, audio: bytes, filename: str = "audio.webm") -> str:
        """Speech to text via Whisper, for the chat's dictation button."""
        if not audio:
            raise LLMError("no audio received")
        try:
            result = self._client.audio.transcriptions.create(
                file=(filename, audio), model=config.TRANSCRIPTION_MODEL
            )
        except Exception as exc:
            raise LLMError(_scrub(f"transcription failed: {exc}")) from exc
        return (result.text or "").strip()

    def _with_retries(self, messages: list[dict], max_tokens: int, model: str | None = None):
        backoff = config.INITIAL_BACKOFF_SECONDS
        last_error: Exception | None = None

        for attempt in range(config.MAX_RETRIES):
            try:
                return self._client.chat.completions.create(
                    model=model or self._model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=self._temperature,
                )
            except RateLimitError as exc:
                if DAILY_LIMIT.search(str(exc)):
                    raise _OutForToday(str(exc), _reset_seconds(str(exc))) from exc
                last_error = exc
                if attempt == config.MAX_RETRIES - 1:
                    break
                time.sleep(backoff)
                backoff *= 2
            except Exception as exc:
                raise LLMError(_scrub(f"completion failed: {exc}")) from exc

        raise LLMError(_scrub(
            f"rate limited after {config.MAX_RETRIES} attempts: {last_error}"
        ))
