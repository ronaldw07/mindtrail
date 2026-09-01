"""Search and fetch tests. All network access is stubbed."""

import pytest

from mindtrail.ingest.fetch import html_to_text
from mindtrail.ingest.search import (
    FallbackSearch,
    SearchError,
    SearchResult,
)


class StubProvider:
    def __init__(self, results=None, error=None):
        self._results = results or []
        self._error = error
        self.calls = 0

    def search(self, query, max_results):
        self.calls += 1
        if self._error:
            raise SearchError(self._error)
        return self._results[:max_results]


def a_result(url="http://a.com"):
    return SearchResult(title="t", url=url, snippet="s")


def test_fallback_uses_the_first_provider_that_works():
    primary = StubProvider(error="rate limited")
    secondary = StubProvider(results=[a_result("http://second.com")])

    results = FallbackSearch([primary, secondary]).search("q", 3)

    assert results[0].url == "http://second.com"


def test_fallback_skips_a_provider_returning_nothing():
    empty = StubProvider(results=[])
    working = StubProvider(results=[a_result("http://works.com")])

    results = FallbackSearch([empty, working]).search("q", 3)

    assert results[0].url == "http://works.com"


def test_fallback_does_not_call_later_providers_once_one_succeeds():
    working = StubProvider(results=[a_result()])
    unused = StubProvider(results=[a_result()])

    FallbackSearch([working, unused]).search("q", 3)

    assert unused.calls == 0


def test_fallback_raises_when_every_provider_fails():
    with pytest.raises(SearchError):
        FallbackSearch([StubProvider(error="down")]).search("q", 3)


def test_fallback_requires_a_provider():
    with pytest.raises(ValueError):
        FallbackSearch([])


def test_script_and_style_contents_are_stripped():
    html = "<html><body><script>var x=1;</script><p>Real text</p>"
    html += "<style>.a{color:red}</style></body></html>"

    assert html_to_text(html) == "Real text"


def test_text_is_truncated_to_the_limit():
    html = f"<p>{'word ' * 5000}</p>"

    assert len(html_to_text(html, max_chars=100)) == 100


def test_whitespace_between_tags_is_collapsed():
    html = "<p>  first  </p>\n\n<p>   second   </p>"

    assert html_to_text(html) == "first second"
