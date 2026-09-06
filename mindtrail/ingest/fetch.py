"""Fetch a page and reduce it to readable text.

Uses only the standard library plus Python's HTML parser, so there is no
extra dependency for what is a fairly small job.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from html.parser import HTMLParser
from urllib.parse import urlsplit

USER_AGENT = "Mozilla/5.0 (compatible; mindtrail/0.1)"
ALLOWED_SCHEMES = ("http", "https")
TIMEOUT_SECONDS = 15
IGNORED_TAGS = frozenset({"script", "style", "noscript", "svg", "head"})
MAX_CHARS = 6000

# Redirect hops a single fetch will follow before giving up. Bounded so a
# redirect loop (accidental or adversarial) can't hang a request forever.
MAX_REDIRECTS = 5

# Only one fetch runs at a time: _pinned_resolution below monkeypatches
# socket.getaddrinfo for the process, not just this module, for the
# duration of a request. That patch is safe for unrelated callers (it
# transparently falls through to the real resolver for any host it
# hasn't specifically pinned), but two fetches racing to install and
# restore that patch at the same time would not be. This lock serializes
# fetch_url against itself; it says nothing about, and does not block,
# unrelated network calls elsewhere in the process.
_fetch_lock = threading.Lock()


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
    """Raised when a page could not be retrieved, or was refused."""


def html_to_text(html: str, max_chars: int = MAX_CHARS) -> str:
    """Strip markup, collapse whitespace, and truncate.

    Truncation matters: the free tier allows only ~12K tokens per minute,
    so whole pages cannot be fed to the model.
    """
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text[:max_chars]


# --- SSRF guard -------------------------------------------------------
#
# fetch_url used to only ever see URLs a search provider generated -
# effectively trusted input. Saving a URL to memory changes that: a user
# now pastes an arbitrary URL into a browser form that reaches this
# function directly, on a server that (per the auth support already in
# this app) can be deployed somewhere non-local. That is a textbook SSRF
# vector - a pasted URL could target cloud instance metadata
# (169.254.169.254), a service bound to 127.0.0.1, or an internal
# RFC1918 address, and have this server fetch it on the submitter's
# behalf.
#
# Every hostname this module connects to - the original URL and every
# redirect hop, since urllib follows redirects on its own by default -
# is resolved and checked against ipaddress's private/loopback/
# link-local/reserved/multicast ranges before a connection is made.
# Resolution and validation happen immediately before connecting, with
# the result pinned (see _pinned_resolution) so the address actually
# connected to is the one just checked - not a second, independent DNS
# lookup that a TTL=0 record could legitimately answer differently a
# moment later ("DNS rebinding"). Do not "simplify" this back down to a
# single check on the original URL; that is precisely the gap a redirect
# or a rebinding attack walks through.


def _reject_if_unsafe(ip_str: str) -> None:
    """Raise FetchError unless `ip_str` is a globally routable address.

    Covers both IPv4 and IPv6: is_private catches RFC1918 and the IPv6
    unique-local range, is_loopback catches 127.0.0.0/8 and ::1,
    is_link_local catches 169.254.0.0/16 (what makes cloud metadata
    endpoints unreachable) and fe80::/10, is_reserved and is_multicast
    catch the remaining special-use ranges, and is_unspecified catches
    0.0.0.0 / ::.
    """
    ip = ipaddress.ip_address(ip_str)
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise FetchError(f"refusing to fetch a non-public address: {ip_str}")


def _default_port(scheme: str, explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    return 443 if scheme == "https" else 80


def _validated_target(url: str) -> tuple[str, int]:
    """Scheme-check a URL and return (hostname, port).

    Shared by the entry-point check in fetch_url and the redirect
    handler below, so a redirect gets exactly the same scheme guard the
    original URL did.
    """
    parsed = urlsplit(url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        raise FetchError(f"refusing non-http(s) url: {url}")
    return parsed.hostname, _default_port(parsed.scheme, parsed.port)


def _resolve_and_validate(hostname: str, port: int, pinned: dict) -> None:
    """Resolve `hostname` once, reject it if any address is unsafe, and
    record the (TCP-only) result into `pinned` so the connection this
    validation is for reuses these exact addresses instead of a second,
    independent lookup.
    """
    try:
        infos = socket.getaddrinfo(hostname, port, 0, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"could not resolve host: {hostname}") from exc
    if not infos:
        raise FetchError(f"could not resolve host: {hostname}")
    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        _reject_if_unsafe(sockaddr[0])
    pinned[hostname] = infos


@contextmanager
def _pinned_resolution():
    """Pin socket.getaddrinfo for the duration of one fetch (including
    every redirect hop it follows) so a hostname already validated by
    _resolve_and_validate resolves to the exact same addresses when the
    connection is actually opened a moment later, instead of a fresh
    lookup that could legitimately answer differently.

    Any host not explicitly pinned here (i.e. every unrelated caller
    elsewhere in the process) falls straight through to the real
    resolver, unaffected.
    """
    pinned: dict[str, list[tuple]] = {}
    real_getaddrinfo = socket.getaddrinfo

    def patched(host, *args, **kwargs):
        if host in pinned:
            return pinned[host]
        return real_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = patched
    try:
        yield pinned
    finally:
        socket.getaddrinfo = real_getaddrinfo


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validates the target of every redirect hop before following it.

    urllib follows redirects automatically; without this, a URL that
    starts out public and 302s to http://169.254.169.254/ would sail
    straight through, past the check the original URL got.
    """

    max_redirections = MAX_REDIRECTS

    def __init__(self, pinned: dict) -> None:
        self._pinned = pinned

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        hostname, port = _validated_target(newurl)
        _resolve_and_validate(hostname, port, self._pinned)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_html(url: str) -> str:
    """Return the raw, decoded HTML for a URL, or raise FetchError.

    fetch_url (below) is the general-purpose caller - question research,
    where only cleaned text ever matters. Saving a URL to memory needs
    the real markup too, to read the page's <title> before html_to_text
    discards it outright (it lives inside <head>, which html_to_text
    treats as ignorable boilerplate).

    See the SSRF guard block above for why the scheme, hostname, and
    every redirect target are validated before anything is connected to.
    """
    hostname, port = _validated_target(url)

    with _fetch_lock, _pinned_resolution() as pinned:
        _resolve_and_validate(hostname, port, pinned)

        opener = urllib.request.build_opener(_SafeRedirectHandler(pinned))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
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


def fetch_url(url: str, max_chars: int = MAX_CHARS) -> str:
    """Return readable text from a URL, or raise FetchError."""
    return html_to_text(fetch_html(url), max_chars=max_chars)


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
TITLE_MAX_CHARS = 200


def extract_title(page_html: str) -> str | None:
    """The page's <title> text, decoded and whitespace-collapsed, or
    None if it has none.

    A regex rather than another HTMLParser pass: this only ever needs
    the first <title>...</title> pair, and a full parse for that would
    rebuild _TextExtractor's whole tag-tracking machinery to answer a
    much narrower question.
    """
    match = _TITLE_RE.search(page_html)
    if not match:
        return None
    title = " ".join(html.unescape(match.group(1)).split())
    return title[:TITLE_MAX_CHARS] or None
