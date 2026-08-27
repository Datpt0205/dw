"""Turning a URL into readable prose, with the standard library.

HTML is reduced with ``html.parser`` on purpose: the API image ships no parser
stack (``docling`` is a worker-only extra that drags in torch), and a legal page
is prose in ``<p>`` tags, not a layout problem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

from dw_kernel.net_guard import OutboundUrlError, ensure_allowed_outbound_url

# \xa0 spelled out: HTML is full of &nbsp; and a literal one is invisible here.
_WHITESPACE = re.compile("[ \t\xa0]+")
_BLANKLINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class FetchPolicy:
    """Limits on one outbound page read.

    Separate from any source policy: how big a page may be and how long we wait
    is a property of fetching, not of what the page is about.
    """

    max_bytes: int
    timeout_seconds: float
    accept_content_types: tuple[str, ...]


class _TextExtractor(HTMLParser):
    """Visible text only: script/style dropped, block tags become newlines."""

    # Chrome as well as code: measured on real legal pages, anchor terms occur
    # in nav menus and sidebars, and a window cut there is a passage of link
    # text that no quote will ever be found in.
    #
    # ``form`` is deliberately NOT here. ASP.NET WebForms — which both
    # vanban.chinhphu.vn and vbpl.vn are built on — wraps the entire page body in
    # a single ``<form runat="server">``, so skipping it empties the document:
    # measured 2026-08-24, vanban.chinhphu.vn went from 5,809 characters to 48.
    # Individual controls are dropped instead.
    _SKIP = frozenset(
        {
            "script",
            "style",
            "noscript",
            "template",
            "svg",
            "nav",
            "header",
            "footer",
            "aside",
            "button",
            "select",
            "iframe",
        }
    )
    _BREAK = frozenset(
        {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    @property
    def text(self) -> str:
        joined = _WHITESPACE.sub(" ", "".join(self._parts))
        return _BLANKLINES.sub("\n\n", "\n".join(line.strip() for line in joined.split("\n")))


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text.strip()


@dataclass(frozen=True)
class FetchedPage:
    url: str
    text: str
    source_version: str


@dataclass
class PageFetcher:
    """One GET, capped and type-checked, returning readable text."""

    policy: FetchPolicy
    allow_private: bool = False

    async def fetch(self, url: str) -> FetchedPage | None:
        try:
            # These URLs come from a search engine, not from configuration, so
            # the guard runs per URL rather than once at wiring time. It is
            # inside the try because a search result pointing somewhere it
            # should not is one bad result, not a reason to fail the query —
            # outside, it was the one fetch failure that escaped the caller.
            ensure_allowed_outbound_url(url, allow_private=self.allow_private)
            async with httpx.AsyncClient(
                timeout=self.policy.timeout_seconds, follow_redirects=True
            ) as client:
                response = await client.get(url, headers={"Accept": "text/html,text/plain"})
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if content_type.lower() not in self.policy.accept_content_types:
                    return None
                raw = response.content
        except (httpx.HTTPError, OutboundUrlError):
            # One unreachable source must not sink the query; the caller has
            # other hits, and no citation at all is already handled downstream.
            return None
        if len(raw) > self.policy.max_bytes:
            return None
        try:
            html = raw.decode(response.encoding or "utf-8", errors="replace")
        except (LookupError, UnicodeDecodeError):  # pragma: no cover - defensive
            return None
        text = html_to_text(html) if content_type.lower() != "text/plain" else html.strip()
        if not text:
            return None
        stamp = response.headers.get("last-modified") or response.headers.get("etag") or ""
        return FetchedPage(url=url, text=text, source_version=version_label(stamp))


def version_label(stamp: str) -> str:
    """What identifies this revision of the page, for citation and comparison."""
    cleaned = stamp.strip().strip('"')
    return f"web:{cleaned}" if cleaned else "web:unversioned"
