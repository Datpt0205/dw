"""Composition root: the only place concrete adapters are wired together.

Tests build their own container with fake ports; production wiring lives here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.mock_model import MockModelAdapter
from dw_agent_runtime.adapters.openai_compatible import OpenAICompatibleAdapter
from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore
from dw_agent_runtime.adapters.tool_execution_store import SqlToolExecutionStore
from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.model.gateway import (
    InMemoryUsageRecorder,
    ModelProviderAdapter,
    RoutingModelGateway,
)
from dw_agent_runtime.model.profiles import ModelProfileRegistry
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.tools import ToolRegistry
from dw_api.health import HealthService, database_probe
from dw_api.settings import ApiSettings
from dw_connectors.adapters.mock_task_connector import MockTaskConnectorAdapter
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_memory.policy import MemoryWritePolicy
from dw_memory.service import MemoryService
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.identity.keycloak import KeycloakTokenVerifier
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.identity import DbAccessContextFactory
from dw_platform.application.ports import (
    AccessContextFactoryPort,
    PlatformUnitOfWorkFactory,
    TokenVerifierPort,
)
from dw_work_ops.adapters.dispatch.tool import DispatchToolFactory
from dw_work_ops.adapters.organization.directory import SqlOrganizationDirectory
from dw_work_ops.adapters.persistence.repositories import SqlWorkOpsUnitOfWorkFactory
from dw_work_ops.application.handlers import (
    CreateMeetingHandler,
    GenerateActionsHandler,
    GetMeetingHandler,
    ListMeetingsHandler,
)
from dw_work_ops.domain.policies import CanAutoDispatchAction
from dw_work_ops.workflows.registry import register_work_ops_graphs
from dw_work_ops.workflows.v1.services import WorkOpsWorkflowServices

REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass
class WorkOpsHandlers:
    create_meeting: CreateMeetingHandler
    get_meeting: GetMeetingHandler
    list_meetings: ListMeetingsHandler
    generate_actions: GenerateActionsHandler


@dataclass
class ApiContainer:
    """Wired dependencies for the API process."""

    settings: ApiSettings
    engine: AsyncEngine | None
    health_service: HealthService
    token_verifier: TokenVerifierPort | None
    access_context_factory: AccessContextFactoryPort | None
    uow_factory: PlatformUnitOfWorkFactory | None
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService
    run_store: SqlWorkerRunStore | None = None
    approval_flow: ApproveAndResumeService | None = None
    work_ops: WorkOpsHandlers | None = None

    def run_context_for(self, context: AccessContext, run_id: uuid.UUID) -> RunContext:
        return RunContext(
            run_id=run_id,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            actor_id=context.principal_id,
            worker_id="lookup",
            worker_version="0.0.0",
            channel="web",
            plan_id=context.plan_id,
            roles=context.roles,
            scopes=context.scopes,
            trace_id=f"api-{run_id.hex[:12]}",
        )

    async def shutdown(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


def _build_token_verifier(settings: ApiSettings) -> TokenVerifierPort | None:
    if settings.auth_mode == "oidc":
        assert settings.oidc_issuer_url is not None  # validate_for_profile enforced
        return KeycloakTokenVerifier(settings.oidc_issuer_url, settings.oidc_audience)
    if settings.dev_secret:
        return DevTokenVerifier(settings.dev_secret)
    return None  # auth disabled until a secret is configured (local only)


def _build_model_adapters(settings: ApiSettings) -> dict[str, ModelProviderAdapter]:
    adapters: dict[str, ModelProviderAdapter] = {}
    if settings.model_provider == "mock":
        if settings.profile == "production":
            raise RuntimeError("the mock model provider is forbidden in production (ADR-012)")
        adapters["mock"] = MockModelAdapter(
            fixtures_dir=REPO_ROOT / "evals" / "fixtures" / "mock_model"
        )
    if settings.openai_api_key and settings.openai_base_url:
        adapters["openai_compatible"] = OpenAICompatibleAdapter(
            base_url=settings.openai_base_url, api_key=settings.openai_api_key
        )
    if settings.profile == "production" and "openai_compatible" not in adapters:
        raise RuntimeError("production requires a real model provider")
    return adapters


def _build_storage(settings: ApiSettings) -> object | None:
    if not settings.s3_endpoint_url:
        return None
    from minio import Minio

    from dw_knowledge.adapters.minio_storage import MinioObjectStorageAdapter

    endpoint = settings.s3_endpoint_url.replace("http://", "").replace("https://", "")
    client = Minio(
        endpoint,
        access_key=settings.s3_access_key or "",
        secret_key=settings.s3_secret_key or "",
        secure=settings.s3_endpoint_url.startswith("https://"),
    )
    return MinioObjectStorageAdapter(client=client, bucket=settings.s3_bucket)


def build_container(settings: ApiSettings | None = None) -> ApiContainer:
    settings = settings or ApiSettings()
    settings.validate_for_profile()

    clock = SystemClock()
    id_generator = Uuid4Generator()
    authorization = ScopeAuthorizationService()
    entitlement = PlanEntitlementService(DEFAULT_PLANS)

    engine: AsyncEngine | None = None
    access_context_factory: AccessContextFactoryPort | None = None
    uow_factory: PlatformUnitOfWorkFactory | None = None
    run_store: SqlWorkerRunStore | None = None
    approval_flow: ApproveAndResumeService | None = None
    work_ops: WorkOpsHandlers | None = None

    if settings.database_url:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        access_context_factory = DbAccessContextFactory(SqlMembershipLookup(session_factory))
        uow_factory = SqlPlatformUnitOfWorkFactory(session_factory)
        run_store = SqlWorkerRunStore(session_factory)

        storage = _build_storage(settings)
        if storage is not None:
            # ---- model gateway -------------------------------------------
            profiles = ModelProfileRegistry()
            profiles.load_directory(REPO_ROOT / "configs" / "models")
            prompts = PromptRegistry()
            prompts.load_directory(REPO_ROOT / "configs" / "prompts")
            gateway = RoutingModelGateway(
                profiles=profiles,
                prompts=prompts,
                adapters=_build_model_adapters(settings),
                usage_recorder=InMemoryUsageRecorder(),
            )

            # ---- tools ----------------------------------------------------
            tool_registry = ToolRegistry()
            tool_registry.register(DispatchToolFactory(MockTaskConnectorAdapter()).build())
            tool_executor = ToolExecutor(
                registry=tool_registry,
                execution_store=SqlToolExecutionStore(session_factory),
                uow_factory=uow_factory,
                clock=clock,
                id_generator=id_generator,
            )

            # ---- work_ops workflow ---------------------------------------
            from dw_work_ops.application.ports import TranscriptStoragePort

            assert isinstance(storage, object)
            work_ops_uow_factory = SqlWorkOpsUnitOfWorkFactory(session_factory)
            services = WorkOpsWorkflowServices(
                uow_factory=work_ops_uow_factory,
                storage=storage,  # type: ignore[arg-type]
                directory=SqlOrganizationDirectory(session_factory),
                model_gateway=gateway,
                tool_executor=tool_executor,
                memory_service=MemoryService(
                    session_factory=session_factory,
                    policy=MemoryWritePolicy(),
                    clock=clock,
                    id_generator=id_generator,
                ),
                dispatch_policy=CanAutoDispatchAction(),
                clock=clock,
                id_generator=id_generator,
            )
            graph_registry = GraphRegistry()
            register_work_ops_graphs(graph_registry, services)
            worker_registry = WorkerRegistry(graph_registry=graph_registry)
            worker_registry.load_directory(REPO_ROOT / "configs" / "workers")

            runner = LangGraphWorkflowRunner(
                worker_registry=worker_registry,
                graph_registry=graph_registry,
                checkpoint_saver=SqlAlchemyCheckpointSaver(session_factory),
                run_store=run_store,
                uow_factory=uow_factory,
                clock=clock,
                id_generator=id_generator,
            )
            approval_flow = ApproveAndResumeService(
                uow_factory=uow_factory,
                runner=runner,
                run_store=run_store,
                clock=clock,
                id_generator=id_generator,
            )

            storage_port: TranscriptStoragePort = storage  # type: ignore[assignment]
            work_ops = WorkOpsHandlers(
                create_meeting=CreateMeetingHandler(
                    uow_factory=work_ops_uow_factory,
                    storage=storage_port,
                    authorization=authorization,
                    entitlement=entitlement,
                    clock=clock,
                    id_generator=id_generator,
                ),
                get_meeting=GetMeetingHandler(
                    uow_factory=work_ops_uow_factory, authorization=authorization
                ),
                list_meetings=ListMeetingsHandler(
                    uow_factory=work_ops_uow_factory, authorization=authorization
                ),
                generate_actions=GenerateActionsHandler(
                    uow_factory=work_ops_uow_factory,
                    workflow_runner=runner,
                    authorization=authorization,
                    entitlement=entitlement,
                    id_generator=id_generator,
                ),
            )
    elif settings.profile == "production":
        settings.require_database_url()

    return ApiContainer(
        settings=settings,
        engine=engine,
        health_service=HealthService(probes={"database": database_probe(engine)}),
        token_verifier=_build_token_verifier(settings),
        access_context_factory=access_context_factory,
        uow_factory=uow_factory,
        authorization=authorization,
        entitlement=entitlement,
        run_store=run_store,
        approval_flow=approval_flow,
        work_ops=work_ops,
    )
