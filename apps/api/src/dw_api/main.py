"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import dw_api
from dw_api.bootstrap import ApiContainer, build_container
from dw_api.exception_handlers import register_exception_handlers
from dw_api.middleware.rate_limit import RateLimitMiddleware
from dw_api.middleware.request_id import RequestIdMiddleware
from dw_api.routes.v1.approvals import router as approvals_router
from dw_api.routes.v1.audit import router as audit_router
from dw_api.routes.v1.auth import router as auth_router
from dw_api.routes.v1.health import build_health_router
from dw_api.routes.v1.integrations import router as integrations_router
from dw_api.routes.v1.knowledge import router as knowledge_router
from dw_api.routes.v1.me import router as me_router
from dw_api.routes.v1.memory import router as memory_router
from dw_api.routes.v1.runs import router as runs_router


def _configure_logging() -> None:
    """Make the background loops audible.

    Uvicorn configures its own access logger and leaves the root at WARNING, so
    everything this app logs at INFO — the mailroom, the Zalo poller, the law
    watch, which sites a legal question was answered from — was being written
    and discarded. Nothing was broken; it just could not be seen.
    """
    logging.basicConfig(
        level=os.environ.get("DW_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    # httpx logs one line per request at INFO. The Zalo channel long-polls
    # several times a second and the bot token rides in the URL, so leaving it
    # on both drowns everything else and writes a credential into the log on
    # every poll. Failures still surface: they are logged by whoever made the
    # call, with the secret already stripped.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def create_app(container: ApiContainer | None = None) -> FastAPI:
    _configure_logging()
    container = container or build_container()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        bot_task = None
        slack_task = None
        settings = container.settings
        if (
            settings.telegram_bot_token
            and settings.profile != "test"
            and container.work_ops is not None
        ):
            from dw_api.bootstrap import REPO_ROOT
            from dw_api.channels.telegram import start_telegram_bot

            bot_task = start_telegram_bot(container, settings.telegram_bot_token, REPO_ROOT)
        if container.chat is not None and settings.profile != "test":
            from dw_api.bootstrap import REPO_ROOT
            from dw_api.channels.slack import start_slack_front_office

            slack_task = start_slack_front_office(
                container, container.chat, REPO_ROOT, service=app.state.slack_front_office
            )
        mailroom_task = None
        zalo_task = None
        warmup_task = None
        law_watch_task = None
        if settings.profile != "test":
            from dw_api.bootstrap import REPO_ROOT
            from dw_api.channels.law_watch import start_law_watch
            from dw_api.channels.mailroom import start_mailroom
            from dw_api.channels.zalo import start_zalo_front_office
            from dw_api.warmup import start_model_warmup

            mailroom_task = start_mailroom(container, REPO_ROOT)
            zalo_task = start_zalo_front_office(container, REPO_ROOT)
            warmup_task = start_model_warmup(settings.embed_url, settings.rerank_url)
            law_watch_task = start_law_watch(container, REPO_ROOT)
        try:
            yield
        finally:
            if bot_task is not None:
                bot_task.cancel()
            if slack_task is not None:
                slack_task.cancel()
            if mailroom_task is not None:
                mailroom_task.cancel()
            if zalo_task is not None:
                zalo_task.cancel()
            if warmup_task is not None:
                warmup_task.cancel()
            if law_watch_task is not None:
                law_watch_task.cancel()
            await container.shutdown()

    app = FastAPI(
        title="Digital Worker Platform API",
        version=dw_api.__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.container = container
    # Slack front office: one service instance shared by the Socket Mode task
    # and (when a signing secret is configured) the HTTPS ingress (P8).
    app.state.slack_front_office = None
    if container.chat is not None:
        from dw_api.bootstrap import REPO_ROOT
        from dw_api.channels.slack import build_front_office

        app.state.slack_front_office = build_front_office(container, container.chat, REPO_ROOT)
        if container.settings.slack_signing_secret:
            from dw_api.routes.v1.slack_channel import build_slack_channel_router
            from dw_connectors.adapters.slack_signature import SlackSignatureVerifier

            app.include_router(
                build_slack_channel_router(
                    app.state.slack_front_office,
                    SlackSignatureVerifier(container.settings.slack_signing_secret),
                ),
                prefix="/api/v1",
            )
    # Middleware runs in reverse registration order: request-id first, then limit.
    app.add_middleware(
        RateLimitMiddleware, requests_per_minute=container.settings.rate_limit_per_minute
    )
    app.add_middleware(RequestIdMiddleware)
    # Browser clients (web on :3000) are cross-origin; production must list
    # origins explicitly, local/test default to the dev web origin.
    cors_origins = container.settings.cors_origins
    if not cors_origins and container.settings.profile != "production":
        cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    if cors_origins:
        from starlette.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-Tenant-Id",
                "X-Workspace-Id",
                "Idempotency-Key",
            ],
            expose_headers=["X-Request-ID", "Retry-After"],
        )
    register_exception_handlers(app)
    app.include_router(build_health_router(container.health_service), prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(me_router, prefix="/api/v1")
    app.include_router(approvals_router, prefix="/api/v1")
    app.include_router(runs_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(integrations_router, prefix="/api/v1")
    # Demo helpers — never mounted in production (ADR-013). The sample-data
    # endpoints use the normal authenticated context, so they also work under
    # OIDC; the dev-token issuer (/dev/session) stays gated to dev auth mode so
    # it is never a Keycloak bypass.
    settings = container.settings
    if settings.profile != "production":
        from dw_api.bootstrap import REPO_ROOT
        from dw_api.routes.v1.dev import build_dev_router

        include_session = settings.auth_mode == "dev" and bool(settings.dev_secret)
        app.include_router(
            build_dev_router(REPO_ROOT, settings.dev_secret or "", include_session=include_session),
            prefix="/api/v1",
        )
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
    if container.tender is not None:
        from dw_api.dependencies.auth import get_access_context as get_ctx
        from dw_tender.presentation.api import build_procurement_router

        app.include_router(
            build_procurement_router(
                create_case=container.tender.create_case,
                get_case=container.tender.get_case,
                list_cases=container.tender.list_cases,
                analyze_case=container.tender.analyze_case,
                access_context_dependency=get_ctx,
            ),
            prefix="/api/v1",
        )
    if container.preparation is not None:
        from dw_api.dependencies.auth import get_access_context as get_prep_ctx
        from dw_tender.presentation.preparation_api import build_preparation_router

        app.include_router(
            build_preparation_router(
                create_case=container.preparation.create_case,
                get_case=container.preparation.get_case,
                list_cases=container.preparation.list_cases,
                run_case=container.preparation.run_case,
                verify_intake=container.preparation.verify_intake,
                reject_intake=container.preparation.reject_intake,
                answer_clarifications=container.preparation.answer_clarifications,
                record_publication=container.preparation.record_publication,
                auto_publish=container.preparation.auto_publish,
                record_submission=container.preparation.record_submission,
                complete_cp4=container.preparation.complete_cp4,
                submit_addendum=container.preparation.submit_addendum,
                decide_cp3=container.preparation.decide_cp3,
                audit_recorder=container.preparation.audit_recorder,
                assess_rework=container.preparation.assess_rework,
                list_pending_explanations=container.preparation.list_pending_explanations,
                submit_explanation=container.preparation.submit_explanation,
                decide_explanation=container.preparation.decide_explanation,
                void_rework_event=container.preparation.void_rework_event,
                access_context_dependency=get_prep_ctx,
                handoff_to_evaluation=container.preparation.handoff_to_evaluation,
            ),
            prefix="/api/v1",
        )
    return app


app = create_app()
