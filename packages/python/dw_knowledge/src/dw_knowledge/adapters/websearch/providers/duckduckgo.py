"""DuckDuckGo, with the caveat stated plainly.

DuckDuckGo publishes no API that returns web results — the documented one
answers instant-answer queries and returns nothing for "thời gian chuẩn bị hồ sơ
dự thầu". The only way to get results is to read the HTML page a browser would
get, which is what this does.

That makes it the least dependable link in the chain, and it is configured last
and disabled by default for exactly that reason. It has no service commitment,
its markup can change without notice, and a chain that leans on it is a chain
that will quietly stop finding law one Tuesday.

**If DuckDuckGo blocks us, we drop it.** No rotating user agents, no proxies, no
pretending to be something we are not. The same rule already cost this system
``thuvienphapluat.vn``, which 403s every request: a source that has said no is a
source we do not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import httpx

from dw_kernel.resilience import CircuitBreaker
from dw_knowledge.adapters.websearch.contracts import SearchHit, SearchParams
from dw_knowledge.adapters.websearch.providers import _http

DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"


def _direct_url(href: str) -> str:
    """Unwrap the ``/l/?uddg=`` redirect DuckDuckGo wraps results in.

    The wrapper is not an obstacle to get around — it is how the page is built,
    and the destination is right there in the query string. A wrapped URL would
    make ``source_uri`` point at a redirector, and a citation a reader cannot
    click through to is not a citation.
    """
    if not href:
        return ""
    if href.startswith("//"):
        href = f"https:{href}"
    split = urlsplit(href)
    if split.path.startswith("/l/"):
        target = parse_qs(split.query).get("uddg", [""])[0]
        return target or ""
    return href if split.scheme in ("http", "https") else ""


class _ResultParser(HTMLParser):
    """Pulls (title, url, snippet) triples out of the results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, str]] = []
        self._url = ""
        self._title: list[str] = []
        self._snippet: list[str] = []
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" and tag not in ("div", "td", "span"):
            return
        classes = dict(attrs).get("class") or ""
        if tag == "a" and "result__a" in classes:
            self._flush()
            self._url = _direct_url(dict(attrs).get("href") or "")
            self._in_title = True
        elif "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if self._in_title and tag == "a":
            self._in_title = False
        elif self._in_snippet and tag in ("a", "div", "td", "span"):
            self._in_snippet = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)
        elif self._in_snippet:
            self._snippet.append(data)

    def _flush(self) -> None:
        if self._url:
            self.rows.append(
                (
                    " ".join("".join(self._title).split()),
                    self._url,
                    " ".join("".join(self._snippet).split()),
                )
            )
        self._url = ""
        self._title = []
        self._snippet = []

    def close(self) -> None:
        super().close()
        self._flush()


@dataclass
class DuckDuckGoProvider:
    timeout_seconds: float = 20.0
    breaker: CircuitBreaker | None = None
    # Injected only by tests: httpx's own seam for exercising a client
    # without a network. Production leaves it None.
    transport: httpx.AsyncBaseTransport | None = None

    @property
    def provider_name(self) -> str:
        return "duckduckgo"

    async def search(self, params: SearchParams) -> list[SearchHit]:
        terms = params.query
        operator = params.site_operator()
        if operator:
            terms = f"{terms} ({operator})"
        response = await _http.request(
            provider=self.provider_name,
            method="POST",
            url=DUCKDUCKGO_URL,
            timeout=self.timeout_seconds,
            breaker=self.breaker,
            transport=self.transport,
            data={"q": terms, "kl": f"{params.country}-{params.language}"},
            headers={"Accept": "text/html"},
        )
        parser = _ResultParser()
        parser.feed(response.text)
        parser.close()
        return [
            SearchHit(title=title, url=url, snippet=snippet, position=index)
            for index, (title, url, snippet) in enumerate(parser.rows[: params.count], start=1)
        ]
