"""Groq client with retry handling.

The free tier allows roughly 30 requests and 12K tokens per minute, so a
long eval sweep will hit 429 partway through. Retrying with exponential
backoff is load-bearing here, not defensive padding.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from groq import Groq, RateLimitError

from mindtrail import config


class LLMError(RuntimeError):
    """Raised when a completion could not be obtained."""


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
        """Single-turn completion, retrying through rate limits."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        response = self._with_retries(messages, max_tokens)
        return Completion(
            text=response.choices[0].message.content or "",
            tokens=response.usage.total_tokens,
            model=self._model,
        )

    def _with_retries(self, messages: list[dict], max_tokens: int):
        backoff = config.INITIAL_BACKOFF_SECONDS
        last_error: Exception | None = None

        for attempt in range(config.MAX_RETRIES):
            try:
                return self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=self._temperature,
                )
            except RateLimitError as exc:
                last_error = exc
                if attempt == config.MAX_RETRIES - 1:
                    break
                time.sleep(backoff)
                backoff *= 2
            except Exception as exc:
                raise LLMError(f"completion failed: {exc}") from exc

        raise LLMError(
            f"rate limited after {config.MAX_RETRIES} attempts: {last_error}"
        )
