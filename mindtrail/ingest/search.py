"""Web search.

DuckDuckGo is scraped rather than served through an official API, so it
rate-limits intermittently. Search is therefore kept behind a small
protocol: when DDG starts refusing, another provider can be added without
touching the researcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ddgs import DDGS


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchError(RuntimeError):
    """Raised when a provider could not return results."""


class SearchProvider(Protocol):
    def search(self, query: str, max_results: int) -> list[SearchResult]: ...


class DuckDuckGoSearch:
    def search(self, query: str, max_results: int) -> list[SearchResult]:
        try:
            raw = DDGS().text(query, max_results=max_results)
        except Exception as exc:  # ddgs raises a variety of transport errors
            raise SearchError(f"DuckDuckGo search failed: {exc}") from exc

        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("href", ""),
                snippet=item.get("body", ""),
            )
            for item in raw
            if item.get("href")
        ]


class FallbackSearch:
    """Tries each provider in order, returning the first non-empty result."""

    def __init__(self, providers: list[SearchProvider]):
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers = tuple(providers)

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        failures: list[str] = []
        for provider in self._providers:
            try:
                results = provider.search(query, max_results)
            except SearchError as exc:
                failures.append(str(exc))
                continue
            if results:
                return results
            failures.append(f"{type(provider).__name__} returned no results")
        raise SearchError("; ".join(failures))


def default_search() -> SearchProvider:
    return FallbackSearch([DuckDuckGoSearch()])
