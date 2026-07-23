"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import dw_api
from dw_api.bootstrap import ApiContainer, build_container
from dw_api.exception_handlers import register_exception_handlers
from dw_api.middleware.request_id import RequestIdMiddleware
from dw_api.routes.v1.approvals import router as approvals_router
from dw_api.routes.v1.audit import router as audit_router
from dw_api.routes.v1.health import build_health_router
from dw_api.routes.v1.me import router as me_router
from dw_api.routes.v1.runs import router as runs_router


def create_app(container: ApiContainer | None = None) -> FastAPI:
    container = container or build_container()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await container.shutdown()

    app = FastAPI(
        title="Digital Worker Platform API",
        version=dw_api.__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.container = container
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(build_health_router(container.health_service), prefix="/api/v1")
    app.include_router(me_router, prefix="/api/v1")
    app.include_router(approvals_router, prefix="/api/v1")
    app.include_router(runs_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    if container.work_ops is not None:
        from dw_api.dependencies.auth import get_access_context
        from dw_work_ops.presentation.api import build_work_ops_router

        app.include_router(
            build_work_ops_router(
                create_meeting=container.work_ops.create_meeting,
                get_meeting=container.work_ops.get_meeting,
                list_meetings=container.work_ops.list_meetings,
                generate_actions=container.work_ops.generate_actions,
                access_context_dependency=get_access_context,
            ),
            prefix="/api/v1",
        )
    return app


app = create_app()
