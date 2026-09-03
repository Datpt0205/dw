"""Google results via serper.dev."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from dw_kernel.resilience import CircuitBreaker
from dw_knowledge.adapters.websearch.contracts import SearchHit, SearchParams
from dw_knowledge.adapters.websearch.providers import _http

SERPER_URL = "https://google.serper.dev/search"


@dataclass
class SerperProvider:
    """Read-only; no side effects to undo.

    Free tier is a one-time grant of credits rather than a monthly allowance, so
    this is first in the default chain: credits already paid for are worth
    spending before an allowance that renews on its own.
    """

    api_key: str
    timeout_seconds: float = 20.0
    breaker: CircuitBreaker | None = None
    # Injected only by tests: httpx's own seam for exercising a client
    # without a network. Production leaves it None.
    transport: httpx.AsyncBaseTransport | None = None

    @property
    def provider_name(self) -> str:
        return "serper"

    async def search(self, params: SearchParams) -> list[SearchHit]:
        terms = params.query
        operator = params.site_operator()
        if operator:
            terms = f"{terms} ({operator})"
        response = await _http.request(
            provider=self.provider_name,
            method="POST",
            url=SERPER_URL,
            timeout=self.timeout_seconds,
            breaker=self.breaker,
            transport=self.transport,
            json={
                "q": terms,
                "gl": params.country,
                "hl": params.language,
                "num": params.count,
            },
            headers={"X-API-KEY": self.api_key},
        )
        data = _http.json_body(response, provider=self.provider_name, breaker=self.breaker)
        organic = data.get("organic") if isinstance(data, dict) else None
        return _http.hits_from(organic, url_key="link", position_key="position")
