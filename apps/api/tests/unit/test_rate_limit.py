"""Rate limit middleware: per-caller fixed window, 429 with Retry-After."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from dw_api.middleware.rate_limit import RateLimitMiddleware

pytestmark = pytest.mark.unit


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def build_app(limit: int, clock: FakeClock) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=limit, clock=clock)

    @app.get("/api/v1/things")
    async def things() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app


async def _get(app: FastAPI, path: str, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


@pytest.mark.anyio
async def test_limits_per_caller_and_recovers_after_window() -> None:
    clock = FakeClock()
    app = build_app(limit=3, clock=clock)

    for _ in range(3):
        assert (await _get(app, "/api/v1/things", token="alice")).status_code == 200
    blocked = await _get(app, "/api/v1/things", token="alice")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.json()["code"] == "rate_limited"

    # a different caller is unaffected
    assert (await _get(app, "/api/v1/things", token="bob")).status_code == 200

    clock.value += 61
    assert (await _get(app, "/api/v1/things", token="alice")).status_code == 200


@pytest.mark.anyio
async def test_health_is_exempt_and_zero_disables() -> None:
    clock = FakeClock()
    app = build_app(limit=1, clock=clock)
    for _ in range(5):
        assert (await _get(app, "/api/v1/health")).status_code == 200

    unlimited = build_app(limit=0, clock=clock)
    for _ in range(5):
        assert (await _get(unlimited, "/api/v1/things", token="x")).status_code == 200
