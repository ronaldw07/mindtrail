"""Fetch a page and reduce it to readable text.

Uses only the standard library plus Python's HTML parser, so there is no
extra dependency for what is a fairly small job.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (compatible; mindtrail/0.1)"
ALLOWED_SCHEMES = ("http://", "https://")
TIMEOUT_SECONDS = 15
IGNORED_TAGS = frozenset({"script", "style", "noscript", "svg", "head"})
MAX_CHARS = 6000


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in IGNORED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in IGNORED_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._chunks.append(stripped)

    @property
    def text(self) -> str:
        return " ".join(self._chunks)


class FetchError(RuntimeError):
    """Raised when a page could not be retrieved."""


def html_to_text(html: str, max_chars: int = MAX_CHARS) -> str:
    """Strip markup, collapse whitespace, and truncate.

    Truncation matters: the free tier allows only ~12K tokens per minute,
    so whole pages cannot be fed to the model.
    """
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text[:max_chars]


def fetch_url(url: str, max_chars: int = MAX_CHARS) -> str:
    """Return readable text from a URL, or raise FetchError.

    Search results are untrusted input, so the scheme is checked before
    the URL reaches urlopen, which would otherwise happily serve file://
    and ftp:// requests.
    """
    if not url.lower().startswith(ALLOWED_SCHEMES):
        raise FetchError(f"refusing non-http(s) url: {url}")

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        OSError,
        # urlopen raises ValueError, not URLError, for a malformed or
        # scheme-less URL. Letting it escape aborts the whole question
        # instead of skipping one bad link.
        ValueError,
    ) as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc

    return html_to_text(html, max_chars=max_chars)
