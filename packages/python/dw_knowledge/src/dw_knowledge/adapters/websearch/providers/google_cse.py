"""Google's own Custom Search JSON API.

Its free allowance renews DAILY rather than monthly, which is why it sits late
in the chain rather than being dropped for being small: a provider that heals
every morning is the one you want still standing when the monthly grants have
been spent halfway through the month.

Needs two secrets, not one — an API key and the id (``cx``) of a Programmable
Search Engine configured to search the whole web. With only one of the two it
is not half-configured, it is unusable, so wiring skips it entirely.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from dw_kernel.resilience import CircuitBreaker
from dw_knowledge.adapters.websearch.contracts import SearchHit, SearchParams
from dw_knowledge.adapters.websearch.providers import _http

GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"

# The API refuses anything above ten per page and errors rather than clamping.
_MAX_COUNT = 10


@dataclass
class GoogleCseProvider:
    api_key: str
    engine_id: str
    timeout_seconds: float = 20.0
    breaker: CircuitBreaker | None = None
    # Injected only by tests: httpx's own seam for exercising a client
    # without a network. Production leaves it None.
    transport: httpx.AsyncBaseTransport | None = None

    @property
    def provider_name(self) -> str:
        return "google_cse"

    async def search(self, params: SearchParams) -> list[SearchHit]:
        terms = params.query
        operator = params.site_operator()
        if operator:
            terms = f"{terms} ({operator})"
        response = await _http.request(
            provider=self.provider_name,
            method="GET",
            url=GOOGLE_CSE_URL,
            timeout=self.timeout_seconds,
            breaker=self.breaker,
            transport=self.transport,
            params={
                "key": self.api_key,
                "cx": self.engine_id,
                "q": terms,
                "num": min(params.count, _MAX_COUNT),
                "gl": params.country,
                "lr": f"lang_{params.language}",
            },
        )
        data = _http.json_body(response, provider=self.provider_name, breaker=self.breaker)
        items = data.get("items") if isinstance(data, dict) else None
        return _http.hits_from(items, url_key="link")
