"""Brave's independent web index.

Its own crawl, not a Google reseller — which is the point of having it second in
the chain. A failover that only rephrases the same index gives you the same
answer when the first one was wrong about a page existing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from dw_kernel.resilience import CircuitBreaker
from dw_knowledge.adapters.websearch.contracts import SearchHit, SearchParams
from dw_knowledge.adapters.websearch.providers import _http

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

# Brave caps a page of results well below what the other engines allow.
_MAX_COUNT = 20


@dataclass
class BraveProvider:
    api_key: str
    timeout_seconds: float = 20.0
    breaker: CircuitBreaker | None = None
    # Injected only by tests: httpx's own seam for exercising a client
    # without a network. Production leaves it None.
    transport: httpx.AsyncBaseTransport | None = None

    @property
    def provider_name(self) -> str:
        return "brave"

    async def search(self, params: SearchParams) -> list[SearchHit]:
        terms = params.query
        operator = params.site_operator()
        if operator:
            # No structured domain filter on this API, so the operator goes in
            # the query like everywhere else. Brave honours ``site:``.
            terms = f"{terms} ({operator})"
        response = await _http.request(
            provider=self.provider_name,
            method="GET",
            url=BRAVE_URL,
            timeout=self.timeout_seconds,
            breaker=self.breaker,
            transport=self.transport,
            params={
                "q": terms,
                "country": params.country,
                "search_lang": params.language,
                "count": min(params.count, _MAX_COUNT),
            },
            headers={
                "X-Subscription-Token": self.api_key,
                "Accept": "application/json",
            },
        )
        data = _http.json_body(response, provider=self.provider_name, breaker=self.breaker)
        web: Any = data.get("web") if isinstance(data, dict) else None
        results = web.get("results") if isinstance(web, dict) else None
        # Brave calls the snippet "description" and does not number its results.
        return _http.hits_from(results, url_key="url", snippet_key="description")
