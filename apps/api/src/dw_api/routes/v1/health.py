"""Health and readiness endpoints under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

import dw_api
from dw_api.health import HealthService


class HealthResponse(BaseModel):
    status: str
    version: str
    api_version: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]


def build_health_router(health_service: HealthService) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok", version=dw_api.__version__, api_version=dw_api.API_VERSION
        )

    @router.get("/ready", response_model=ReadinessResponse)
    async def ready(request: Request, response: Response) -> ReadinessResponse:
        report = await health_service.readiness()
        if not report.ready:
            response.status_code = 503
        return ReadinessResponse(
            status="ready" if report.ready else "not_ready",
            checks=dict(report.checks),
        )

    return router
