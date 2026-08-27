"""The request every provider makes, and the failure taxonomy they share.

Five providers classifying HTTP failures five slightly different ways is five
chances to get it wrong once. In particular the old single-provider client never
caught ``response.json()`` raising on a malformed body: the breaker recorded
neither success nor failure and the exception escaped raw. Doing this in one
place fixes it in one place.
"""

from __future__ import annotations

from typing import Any

import httpx

from dw_kernel.resilience import CircuitBreaker
from dw_knowledge.adapters.websearch.contracts import (
    SearchAuthError,
    SearchHit,
    SearchProviderError,
    SearchQuotaError,
)

# 429 is the honest signal. 403 is what metered free tiers actually send once a
# grant is spent (measured on Serper), so it counts as exhaustion too.
#
# 401 is NOT here, and that was a real bug: a rejected key was reported as "out
# of quota" and put on a six-hour cooldown, so a mistyped key looked exactly
# like a provider to wait out. Measured 2026-08-25 against Tavily, whose keys
# carry a `tvly-` prefix — paste anything else and 401 is what comes back.
_EXHAUSTED_STATUS = frozenset({403, 429})
_AUTH_STATUS = frozenset({401})


async def request(
    *,
    provider: str,
    method: str,
    url: str,
    timeout: float,
    breaker: CircuitBreaker | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """One HTTP round trip, with this provider's failures named.

    A quota error deliberately does NOT call ``record_failure``. The breaker
    exists to notice a service that is unwell; a provider that is merely out of
    credit is perfectly well and will say the same thing in thirty seconds. The
    chain's cooldown owns that case, and letting both mechanisms fire on it
    would only blur which one is speaking.
    """
    if breaker is not None:
        breaker.before_call()
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in _AUTH_STATUS:
            raise SearchAuthError(
                f"{provider}: khoá bị từ chối — kiểm tra lại khoá trong .env",
                details={"provider": provider, "status": str(status)},
            ) from exc
        if status in _EXHAUSTED_STATUS:
            raise SearchQuotaError(
                f"{provider}: hết lượt hoặc key bị từ chối",
                details={"provider": provider, "status": str(status)},
            ) from exc
        if breaker is not None:
            breaker.record_failure()
        raise SearchProviderError(
            f"{provider}: máy chủ tìm kiếm trả lỗi",
            details={"provider": provider, "status": str(status)},
        ) from exc
    except httpx.HTTPError as exc:
        if breaker is not None:
            breaker.record_failure()
        raise SearchProviderError(
            f"{provider}: không gọi được",
            details={"provider": provider, "error": type(exc).__name__},
        ) from exc
    if breaker is not None:
        breaker.record_success()
    return response


def json_body(response: httpx.Response, *, provider: str, breaker: CircuitBreaker | None) -> Any:
    """Parse, and count a body we cannot read as a failure of the service."""
    try:
        return response.json()
    except ValueError as exc:
        if breaker is not None:
            breaker.record_failure()
        raise SearchProviderError(
            f"{provider}: phản hồi không phải JSON hợp lệ",
            details={"provider": provider},
        ) from exc


def hits_from(
    items: Any,
    *,
    url_key: str,
    title_key: str = "title",
    snippet_key: str = "snippet",
    position_key: str | None = None,
) -> list[SearchHit]:
    """Rows a provider returned, reduced to the shape everyone downstream reads.

    Rows that are not dicts, or carry no URL, are dropped rather than raised on:
    one malformed entry in ten results is not a reason to lose the other nine.
    """
    hits: list[SearchHit] = []
    for index, item in enumerate(items or [], start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get(url_key) or "")
        if not url:
            continue
        position = index
        if position_key is not None:
            raw = item.get(position_key)
            if isinstance(raw, int) and raw > 0:
                position = raw
        hits.append(
            SearchHit(
                title=str(item.get(title_key) or ""),
                url=url,
                snippet=str(item.get(snippet_key) or ""),
                position=position,
            )
        )
    return hits
