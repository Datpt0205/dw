"""Tavily — a search API that hands back the page, not just a link to it.

Two things make it worth a slot despite costing more per call.

It takes ``include_domains`` as a real parameter instead of a query operator,
so the allowlist is enforced by the engine rather than hoped for.

It returns ``raw_content``, which lets the fetch step be skipped entirely for
that result. That is the only tool in this chain that gets past a source which
renders with JavaScript — ``vbpl.vn`` returns 56KB of HTML with not one
occurrence of "đấu thầu" in it, and no amount of retrying our own fetcher will
change that.

The content still goes through our own ``passages()`` windowing. Tavily's
chunking is its own, and ``verified_constraint`` accepts a model's quote only
when it appears verbatim in a passage WE cut on sentence boundaries — trusting
someone else's cut is how that check starts failing silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from dw_kernel.resilience import CircuitBreaker
from dw_knowledge.adapters.websearch.contracts import SearchHit, SearchParams
from dw_knowledge.adapters.websearch.providers import _http

TAVILY_URL = "https://api.tavily.com/search"


@dataclass
class TavilyProvider:
    api_key: str
    # "basic" costs one credit, "advanced" two. Basic by default: the extra
    # credit buys Tavily's own passage extraction, which we discard — see
    # ``LegalSourceConfig.tavily_search_depth``.
    search_depth: str = "basic"
    timeout_seconds: float = 30.0  # it fetches pages for us, so it is slower
    breaker: CircuitBreaker | None = None
    # Injected only by tests: httpx's own seam for exercising a client
    # without a network. Production leaves it None.
    transport: httpx.AsyncBaseTransport | None = None

    @property
    def provider_name(self) -> str:
        return "tavily"

    async def search(self, params: SearchParams) -> list[SearchHit]:
        body: dict[str, Any] = {
            "query": params.query,
            "max_results": params.count,
            "search_depth": self.search_depth,
            "include_raw_content": True,
        }
        if params.sites:
            body["include_domains"] = list(params.sites)
        response = await _http.request(
            provider=self.provider_name,
            method="POST",
            url=TAVILY_URL,
            timeout=self.timeout_seconds,
            breaker=self.breaker,
            transport=self.transport,
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        data = _http.json_body(response, provider=self.provider_name, breaker=self.breaker)
        results = data.get("results") if isinstance(data, dict) else None

        hits: list[SearchHit] = []
        for index, item in enumerate(results or [], start=1):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url:
                continue
            raw = item.get("raw_content")
            hits.append(
                SearchHit(
                    title=str(item.get("title") or ""),
                    url=url,
                    snippet=str(item.get("content") or ""),
                    position=index,
                    content=str(raw) if isinstance(raw, str) and raw.strip() else None,
                )
            )
        return hits
