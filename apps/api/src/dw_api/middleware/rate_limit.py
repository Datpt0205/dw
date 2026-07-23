"""Per-caller rate limiting (fixed 60s window, in-process).

Keyed by bearer token when present (per principal) else client IP. This is a
per-process guard for the modular monolith; a multi-instance deployment moves
the counters to Redis behind the same middleware seam (Redis stays a cache —
losing counters only briefly relaxes the limit, never corrupts state).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_WINDOW_SECONDS = 60.0
_EXEMPT_PATHS = ("/api/v1/health", "/api/v1/ready")


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Callable,  # type: ignore[type-arg]
        *,
        requests_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._clock = clock
        self._counters: dict[str, tuple[float, int]] = {}

    def _key(self, request: Request) -> str:
        token = request.headers.get("Authorization")
        if token:
            return hashlib.sha256(token.encode()).hexdigest()[:32]
        client = request.client.host if request.client else "unknown"
        return f"ip:{client}"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._limit <= 0 or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        now = self._clock()
        key = self._key(request)
        window_start, count = self._counters.get(key, (now, 0))
        if now - window_start >= _WINDOW_SECONDS:
            window_start, count = now, 0
        count += 1
        self._counters[key] = (window_start, count)

        if len(self._counters) > 10_000:  # bound memory under key churn
            cutoff = now - _WINDOW_SECONDS
            self._counters = {k: v for k, v in self._counters.items() if v[0] >= cutoff}

        if count > self._limit:
            retry_after = max(1, int(_WINDOW_SECONDS - (now - window_start)))
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "code": "rate_limited",
                    "message": "too many requests, slow down",
                    "details": {"limit_per_minute": str(self._limit)},
                    "request_id": getattr(request.state, "request_id", None),
                },
            )
        return await call_next(request)
