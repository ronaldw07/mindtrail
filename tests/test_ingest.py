"""Search and fetch tests. All network access is stubbed."""

import socket

import pytest

from mindtrail.ingest import fetch as fetch_module
from mindtrail.ingest.fetch import FetchError, extract_title, fetch_url, html_to_text
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


@pytest.mark.parametrize(
    "url", ["/relative/path", "not a url", "javascript:alert(1)", ""]
)
def test_malformed_urls_raise_fetch_error_rather_than_escaping(url):
    # urlopen raises ValueError for these. If it escapes, one bad search
    # result aborts the entire question instead of being skipped.
    with pytest.raises(FetchError):
        fetch_url(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/f"])
def test_non_http_schemes_are_refused(url):
    with pytest.raises(FetchError, match="refusing non-http"):
        fetch_url(url)


def _stub_public_getaddrinfo(host, port=0, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 80))]


def test_transport_errors_become_fetch_error(monkeypatch):
    # The DNS half succeeds (a fake, real-looking public address) so the
    # SSRF guard passes; the failure this test cares about is the actual
    # connection attempt, stubbed to blow up like a dropped connection
    # would.
    monkeypatch.setattr(fetch_module.socket, "getaddrinfo", _stub_public_getaddrinfo)

    def explode(self, *args, **kwargs):
        raise OSError("connection reset")

    monkeypatch.setattr(fetch_module.socket.socket, "connect", explode)

    with pytest.raises(FetchError, match="could not fetch"):
        fetch_url("http://example.com")


# --- SSRF guard ---------------------------------------------------------


def _stub_getaddrinfo_returning(ip):
    def stub(host, port=0, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 80))]

    return stub


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "169.254.169.254",  # cloud instance metadata (link-local)
        "10.1.2.3",  # RFC1918 private
        "192.168.1.1",  # RFC1918 private
        "::1",  # IPv6 loopback
        "fd00::1",  # IPv6 unique-local (is_private)
    ],
)
def test_resolving_to_a_non_public_address_is_refused(monkeypatch, ip):
    monkeypatch.setattr(
        fetch_module.socket, "getaddrinfo", _stub_getaddrinfo_returning(ip)
    )

    with pytest.raises(FetchError, match="non-public"):
        fetch_url("http://looks-public.example.com")


def test_redirect_handler_refuses_a_chain_that_lands_on_a_private_target(monkeypatch):
    # This is the exact gap a check on only the original URL leaves open:
    # a URL that starts out public and 302s to something private. Exercised
    # directly against the redirect handler urllib actually calls on every
    # hop, rather than reconstructing urllib's whole response pipeline.
    monkeypatch.setattr(
        fetch_module.socket, "getaddrinfo",
        _stub_getaddrinfo_returning("169.254.169.254"),
    )
    handler = fetch_module._SafeRedirectHandler(pinned={})

    with pytest.raises(FetchError, match="non-public"):
        handler.redirect_request(
            req=None, fp=None, code=302, msg="Found", headers={},
            newurl="http://internal.example.com/secret",
        )


def test_redirect_hops_are_capped():
    # A redirect loop (accidental or adversarial) must not hang a request
    # forever - urllib enforces this via max_redirections, which the
    # handler sets explicitly rather than trusting urllib's own default.
    assert fetch_module._SafeRedirectHandler.max_redirections == fetch_module.MAX_REDIRECTS
    assert fetch_module.MAX_REDIRECTS <= 5


# --- title extraction (for save-url) ---------------------------------


def test_extract_title_finds_a_simple_title():
    assert extract_title("<html><head><title>Hello World</title></head></html>") == (
        "Hello World"
    )


def test_extract_title_returns_none_when_absent():
    assert extract_title("<html><body>no title here</body></html>") is None


def test_extract_title_collapses_whitespace_and_unescapes_entities():
    html = "<title>\n  Foo &amp;   Bar  \n</title>"
    assert extract_title(html) == "Foo & Bar"


def test_extract_title_is_case_insensitive():
    assert extract_title("<TITLE>Shouting</TITLE>") == "Shouting"
