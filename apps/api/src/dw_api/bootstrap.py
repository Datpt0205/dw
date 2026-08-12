"""Composition root: the only place concrete adapters are wired together.

Tests build their own container with fake ports; production wiring lives here.
"""

from __future__ import annotations

import os
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
from dw_agent_runtime.adapters.openai_responses import OpenAIResponsesAdapter
from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore
from dw_agent_runtime.adapters.telemetry_usage import TelemetryUsageRecorder
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
from dw_connectors.adapters.slack_chat import SlackChatClient
from dw_kernel.net_guard import ensure_allowed_outbound_url
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_kernel.resilience import CircuitBreaker
from dw_knowledge.gateway import KnowledgeGateway
from dw_knowledge.ingest_jobs import IngestJobStore
from dw_knowledge.ports import ObjectStoragePort
from dw_memory.policy import MemoryWritePolicy
from dw_memory.service import MemoryService
from dw_observability.telemetry import NullTelemetry, TelemetryPort
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.identity.keycloak import KeycloakTokenVerifier
from dw_platform.adapters.persistence.identity_provisioning import SqlIdentityBootstrap
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.identity import DbAccessContextFactory
from dw_platform.application.identity_bootstrap import IdentityBootstrapPort
from dw_platform.application.ports import (
    AccessContextFactoryPort,
    PlatformUnitOfWorkFactory,
    TokenVerifierPort,
)
from dw_tender.adapters.conversation.store import SqlConversationStore
from dw_tender.adapters.persistence.repositories import SqlTenderUnitOfWorkFactory
from dw_tender.adapters.policy_loader import load_scoring_policy
from dw_tender.adapters.preparation.repositories import SqlPreparationUnitOfWorkFactory
from dw_tender.adapters.preparation.rules_loader import load_procurement_rules
from dw_tender.application.conversation.service import ConversationIntakeService
from dw_tender.application.handlers import (
    AnalyzeCaseHandler,
    CreateTenderCaseHandler,
    GetTenderCaseHandler,
    ListTenderCasesHandler,
)
from dw_tender.application.preparation.handlers import (
    AnswerPreparationClarificationsHandler,
    AutoPublishPreparationHandler,
    CompletePreparationCp4Handler,
    CreatePreparationCaseHandler,
    DecidePreparationCp3Handler,
    GetPreparationCaseHandler,
    ListPreparationCasesHandler,
    PreparationAuditRecorder,
    ProposePreparationAddendumHandler,
    RecordPreparationPublicationHandler,
    RecordPreparationSubmissionHandler,
    RejectPreparationIntakeHandler,
    RequestCp4Handler,
    RunPreparationHandler,
    SubmitPreparationAddendumHandler,
    VerifyPreparationIntakeHandler,
)
from dw_tender.domain.services.scoring_engine import ScoringEngine
from dw_tender.workflows.preparation_v1.registry import register_preparation_graphs
from dw_tender.workflows.preparation_v1.services import PreparationServices
from dw_tender.workflows.registry import register_tender_graphs
from dw_tender.workflows.v1.services import TenderWorkflowServices
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

# In dev the repo root is derived from the source tree; in containers the
# package lives in site-packages, so the image sets DW_REPO_ROOT=/app and
# ships configs/, evals/fixtures/ and contracts/release/ at that root.
REPO_ROOT = Path(os.environ.get("DW_REPO_ROOT", str(Path(__file__).resolve().parents[4])))


def _release_manifest_ref() -> str:
    """The content-addressed release the API is serving (blueprint §23).

    Generated by ``make release-manifest``; runs record it so results can be
    traced to the exact artifact set. Absent only in un-released dev trees.
    """
    ref_file = REPO_ROOT / "contracts" / "release" / "manifest.ref"
    if ref_file.exists():
        return ref_file.read_text(encoding="utf-8").strip()
    return "unreleased"


@dataclass
class WorkOpsHandlers:
    create_meeting: CreateMeetingHandler
    get_meeting: GetMeetingHandler
    list_meetings: ListMeetingsHandler
    generate_actions: GenerateActionsHandler


@dataclass
class TenderHandlers:
    create_case: CreateTenderCaseHandler
    get_case: GetTenderCaseHandler
    list_cases: ListTenderCasesHandler
    analyze_case: AnalyzeCaseHandler


@dataclass
class PreparationHandlers:
    create_case: CreatePreparationCaseHandler
    get_case: GetPreparationCaseHandler
    list_cases: ListPreparationCasesHandler
    run_case: RunPreparationHandler
    verify_intake: VerifyPreparationIntakeHandler
    reject_intake: RejectPreparationIntakeHandler
    answer_clarifications: AnswerPreparationClarificationsHandler
    record_publication: RecordPreparationPublicationHandler
    auto_publish: AutoPublishPreparationHandler
    record_submission: RecordPreparationSubmissionHandler
    request_cp4: RequestCp4Handler
    complete_cp4: CompletePreparationCp4Handler
    submit_addendum: SubmitPreparationAddendumHandler
    propose_addendum: ProposePreparationAddendumHandler
    decide_cp3: DecidePreparationCp3Handler
    audit_recorder: PreparationAuditRecorder


@dataclass
class ChatFrontOffice:
    """Slack chat front office (conversation-first plan P1) — wired when enabled."""

    app_token: str
    chat_client: SlackChatClient
    conversation_service: ConversationIntakeService
    conversation_store: SqlConversationStore
    slack_user_reverse_map: dict[str, str]


@dataclass
class ApiContainer:
    """Wired dependencies for the API process."""

    settings: ApiSettings
    engine: AsyncEngine | None
    health_service: HealthService
    token_verifier: TokenVerifierPort | None
    access_context_factory: AccessContextFactoryPort | None
    identity_bootstrap: IdentityBootstrapPort | None
    uow_factory: PlatformUnitOfWorkFactory | None
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService
    run_store: SqlWorkerRunStore | None = None
    approval_flow: ApproveAndResumeService | None = None
    work_ops: WorkOpsHandlers | None = None
    tender: TenderHandlers | None = None
    preparation: PreparationHandlers | None = None
    knowledge_gateway: KnowledgeGateway | None = None
    ingest_job_store: IngestJobStore | None = None
    object_storage: ObjectStoragePort | None = None
    memory_service: MemoryService | None = None
    tool_registry: ToolRegistry | None = None
    chat: ChatFrontOffice | None = None
    # Channel-agnostic chat core — shared by Slack (buttons) and Zalo (words).
    conversation_store: SqlConversationStore | None = None
    conversation_service: ConversationIntakeService | None = None

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
        return KeycloakTokenVerifier(
            settings.oidc_issuer_url, settings.oidc_audience, settings.oidc_jwks_url
        )
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
        # SSRF guard: provider endpoints must be public unless local dev.
        ensure_allowed_outbound_url(
            settings.openai_base_url,
            allow_private=settings.outbound_allow_private(),
            allowed_hosts=tuple(settings.outbound_allowed_hosts),
        )
        adapters["openai_compatible"] = OpenAICompatibleAdapter(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            structured_mode=settings.openai_structured_mode,
            breaker=CircuitBreaker(clock=SystemClock(), name="model.openai_compatible"),
        )
        # Responses-dialect adapter (real OpenAI only): same credentials, but
        # /v1/responses returns the model's reasoning summary for visible
        # thinking (ADR-020). Profiles opt in with provider: openai_responses.
        adapters["openai_responses"] = OpenAIResponsesAdapter(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            strict_schema=settings.openai_strict_schema,
            breaker=CircuitBreaker(clock=SystemClock(), name="model.openai_responses"),
        )
    if settings.profile == "production" and "openai_compatible" not in adapters:
        raise RuntimeError("production requires a real model provider")
    return adapters


def _build_telemetry(settings: ApiSettings) -> TelemetryPort:
    """OTel pipeline when configured; Langfuse is just an OTLP endpoint (§21.4)."""
    endpoint = settings.otel_endpoint
    headers: dict[str, str] | None = None
    if settings.langfuse_enabled:
        from dw_observability.langfuse import langfuse_otlp_config

        assert settings.langfuse_host is not None  # validate_for_profile enforced
        assert settings.langfuse_public_key is not None
        assert settings.langfuse_secret_key is not None
        endpoint, headers = langfuse_otlp_config(
            settings.langfuse_host,
            settings.langfuse_public_key,
            settings.langfuse_secret_key,
        )
    if endpoint is None:
        return NullTelemetry()
    from dw_observability.otel import OtelTelemetry, configure_tracing

    tracer, meter = configure_tracing("dw-api", otlp_endpoint=endpoint, otlp_headers=headers)
    return OtelTelemetry(tracer=tracer, meter=meter)


def _build_email_publisher() -> object:
    """SMTP publisher when SMTP_* env is set; otherwise a no-op mock."""
    from dw_tender.adapters.preparation.smtp_publisher import (
        MockEmailPublisher,
        SmtpEmailPublisher,
    )

    host = os.environ.get("SMTP_HOST", "")
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    if host and user and password:
        return SmtpEmailPublisher(
            host=host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=user,
            password=password,
            sender=os.environ.get("SMTP_FROM", user),
        )
    return MockEmailPublisher()


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
    telemetry = _build_telemetry(settings)

    engine: AsyncEngine | None = None
    access_context_factory: AccessContextFactoryPort | None = None
    identity_bootstrap: IdentityBootstrapPort | None = None
    uow_factory: PlatformUnitOfWorkFactory | None = None
    run_store: SqlWorkerRunStore | None = None
    approval_flow: ApproveAndResumeService | None = None
    work_ops: WorkOpsHandlers | None = None
    tender: TenderHandlers | None = None
    preparation: PreparationHandlers | None = None
    knowledge_gateway: KnowledgeGateway | None = None
    ingest_job_store: IngestJobStore | None = None
    object_storage: ObjectStoragePort | None = None
    memory_service: MemoryService | None = None
    tool_registry: ToolRegistry | None = None
    chat: ChatFrontOffice | None = None
    conversation_store: SqlConversationStore | None = None
    conversation_service: ConversationIntakeService | None = None

    if settings.database_url:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        access_context_factory = DbAccessContextFactory(SqlMembershipLookup(session_factory))
        identity_bootstrap = SqlIdentityBootstrap(
            session_factory=session_factory,
            default_tenant_id=uuid.UUID(settings.default_tenant_id),
            default_workspace_id=uuid.UUID(settings.default_workspace_id),
            default_role=settings.default_role,
        )
        uow_factory = SqlPlatformUnitOfWorkFactory(session_factory)
        run_store = SqlWorkerRunStore(session_factory)

        storage = _build_storage(settings)
        if storage is not None:
            # ---- model gateway -------------------------------------------
            profiles = ModelProfileRegistry()
            profiles.load_directory(REPO_ROOT / "configs" / "models")
            prompts = PromptRegistry()
            prompts.load_directory(REPO_ROOT / "configs" / "prompts")
            usage_recorder: InMemoryUsageRecorder | TelemetryUsageRecorder
            if isinstance(telemetry, NullTelemetry):
                usage_recorder = InMemoryUsageRecorder()
            else:
                usage_recorder = TelemetryUsageRecorder(telemetry)
            gateway = RoutingModelGateway(
                profiles=profiles,
                prompts=prompts,
                adapters=_build_model_adapters(settings),
                usage_recorder=usage_recorder,
            )

            # ---- tools ----------------------------------------------------
            if settings.task_connector == "slack":
                from dw_connectors.adapters.slack_task_connector import (
                    SlackTaskConnectorAdapter,
                )

                assert settings.slack_bot_token is not None  # validate_for_profile
                assert settings.slack_default_channel is not None
                task_connector: object = SlackTaskConnectorAdapter(
                    bot_token=settings.slack_bot_token,
                    default_channel=settings.slack_default_channel,
                    breaker=CircuitBreaker(clock=clock, name="connector.slack"),
                )
            else:
                task_connector = MockTaskConnectorAdapter()
            tool_registry = ToolRegistry()
            tool_registry.register(DispatchToolFactory(task_connector).build())  # type: ignore[arg-type]
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
            memory_service = MemoryService(
                session_factory=session_factory,
                policy=MemoryWritePolicy(),
                clock=clock,
                id_generator=id_generator,
            )
            work_ops_uow_factory = SqlWorkOpsUnitOfWorkFactory(session_factory)
            services = WorkOpsWorkflowServices(
                uow_factory=work_ops_uow_factory,
                storage=storage,  # type: ignore[arg-type]
                directory=SqlOrganizationDirectory(session_factory),
                model_gateway=gateway,
                tool_executor=tool_executor,
                memory_service=memory_service,
                dispatch_policy=CanAutoDispatchAction(),
                clock=clock,
                id_generator=id_generator,
                model_profile=settings.model_profile,
            )
            # ---- knowledge gateway (tender evidence retrieval) ------------
            from dw_knowledge.ports import EmbeddingPort, RerankPort, VectorIndexPort

            embeddings: EmbeddingPort
            if settings.embedding_provider == "tei" and settings.embed_url:
                from dw_knowledge.adapters.tei_embedding import TeiEmbeddingAdapter

                embeddings = TeiEmbeddingAdapter(
                    base_url=settings.embed_url, _dimension=settings.embed_dimension
                )
            else:
                from dw_knowledge.adapters.hash_embedding import HashEmbeddingAdapter

                embeddings = HashEmbeddingAdapter()

            reranker: RerankPort | None = None
            if settings.embedding_provider == "tei" and settings.rerank_url:
                from dw_knowledge.adapters.tei_rerank import TeiRerankAdapter

                reranker = TeiRerankAdapter(base_url=settings.rerank_url)

            vector_index: VectorIndexPort
            if settings.qdrant_url:
                from qdrant_client import AsyncQdrantClient

                from dw_knowledge.adapters.qdrant_index import QdrantVectorIndexAdapter

                vector_index = QdrantVectorIndexAdapter(
                    client=AsyncQdrantClient(url=settings.qdrant_url)
                )
            else:
                # Working in-memory fallback (never production — no durability).
                from dw_knowledge.adapters.memory_index import InMemoryVectorIndexAdapter

                vector_index = InMemoryVectorIndexAdapter()
            knowledge_gateway = KnowledgeGateway(
                session_factory=session_factory,
                vector_index=vector_index,
                embeddings=embeddings,
                object_storage=storage,  # type: ignore[arg-type]
                clock=clock,
                id_generator=id_generator,
                reranker=reranker,
            )
            # Upload path: API stages the raw file + enqueues; the worker ingests.
            object_storage = storage  # type: ignore[assignment]
            ingest_job_store = IngestJobStore(
                session_factory=session_factory,
                clock=clock,
                id_generator=id_generator,
            )

            # ---- tender workflow -----------------------------------------
            tender_uow_factory = SqlTenderUnitOfWorkFactory(session_factory)
            scoring_engine = ScoringEngine(
                load_scoring_policy(REPO_ROOT / "configs" / "policies" / "tender_scoring_v1.yaml")
            )
            tender_services = TenderWorkflowServices(
                uow_factory=tender_uow_factory,
                storage=storage,  # type: ignore[arg-type]
                knowledge=knowledge_gateway,
                model_gateway=gateway,
                memory_service=memory_service,
                scoring_engine=scoring_engine,
                clock=clock,
                id_generator=id_generator,
                model_profile=settings.model_profile,
            )

            # ---- DW01 preparation slice ----------------------------------
            preparation_uow_factory = SqlPreparationUnitOfWorkFactory(session_factory)
            procurement_rules = load_procurement_rules(
                REPO_ROOT / "configs" / "policies" / "dw01" / "procurement_rules_v1.yaml"
            )
            preparation_services = PreparationServices(
                uow_factory=preparation_uow_factory,
                storage=storage,  # type: ignore[arg-type]
                rules=procurement_rules,
                # Supplier candidates are case input, never a hidden fixture.
                suppliers=(),
                clock=clock,
                id_generator=id_generator,
                knowledge=knowledge_gateway,
                model_gateway=gateway,
                model_profile=settings.model_profile,
                autonomy_profile=settings.autonomy_profile,
            )

            graph_registry = GraphRegistry()
            register_work_ops_graphs(graph_registry, services)
            register_tender_graphs(graph_registry, tender_services)
            register_preparation_graphs(graph_registry, preparation_services)
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
                release_manifest_ref=_release_manifest_ref(),
                telemetry=telemetry,
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
            tender = TenderHandlers(
                create_case=CreateTenderCaseHandler(
                    uow_factory=tender_uow_factory,
                    storage=storage,  # type: ignore[arg-type]
                    authorization=authorization,
                    entitlement=entitlement,
                    id_generator=id_generator,
                ),
                get_case=GetTenderCaseHandler(
                    uow_factory=tender_uow_factory, authorization=authorization
                ),
                list_cases=ListTenderCasesHandler(
                    uow_factory=tender_uow_factory, authorization=authorization
                ),
                analyze_case=AnalyzeCaseHandler(
                    uow_factory=tender_uow_factory,
                    workflow_runner=runner,
                    authorization=authorization,
                    entitlement=entitlement,
                    id_generator=id_generator,
                ),
            )
            preparation = PreparationHandlers(
                create_case=CreatePreparationCaseHandler(
                    uow_factory=preparation_uow_factory,
                    storage=storage,  # type: ignore[arg-type]
                    authorization=authorization,
                    entitlement=entitlement,
                    id_generator=id_generator,
                    clock=clock,
                    reminder_seconds=settings.approval_reminder_seconds,
                ),
                get_case=GetPreparationCaseHandler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    storage=storage,  # type: ignore[arg-type]
                ),
                list_cases=ListPreparationCasesHandler(
                    uow_factory=preparation_uow_factory, authorization=authorization
                ),
                run_case=RunPreparationHandler(
                    uow_factory=preparation_uow_factory,
                    workflow_runner=runner,
                    authorization=authorization,
                    entitlement=entitlement,
                    id_generator=id_generator,
                ),
                verify_intake=VerifyPreparationIntakeHandler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                    run_case=RunPreparationHandler(
                        uow_factory=preparation_uow_factory,
                        workflow_runner=runner,
                        authorization=authorization,
                        entitlement=entitlement,
                        id_generator=id_generator,
                    ),
                ),
                reject_intake=RejectPreparationIntakeHandler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                ),
                answer_clarifications=AnswerPreparationClarificationsHandler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                ),
                record_publication=RecordPreparationPublicationHandler(
                    uow_factory=preparation_uow_factory,
                    storage=storage,  # type: ignore[arg-type]
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                ),
                auto_publish=AutoPublishPreparationHandler(
                    uow_factory=preparation_uow_factory,
                    storage=storage,  # type: ignore[arg-type]
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                    email_publisher=_build_email_publisher(),  # type: ignore[arg-type]
                    recipient_email=os.environ.get("DW_PUBLICATION_EMAIL", "")
                    or os.environ.get("SMTP_USER", ""),
                ),
                record_submission=RecordPreparationSubmissionHandler(
                    uow_factory=preparation_uow_factory,
                    storage=storage,  # type: ignore[arg-type]
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                ),
                request_cp4=RequestCp4Handler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                ),
                complete_cp4=CompletePreparationCp4Handler(
                    uow_factory=preparation_uow_factory,
                    storage=storage,  # type: ignore[arg-type]
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                ),
                submit_addendum=SubmitPreparationAddendumHandler(
                    uow_factory=preparation_uow_factory,
                    storage=storage,  # type: ignore[arg-type]
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                ),
                propose_addendum=ProposePreparationAddendumHandler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                ),
                decide_cp3=DecidePreparationCp3Handler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                ),
                audit_recorder=PreparationAuditRecorder(
                    uow_factory=uow_factory,
                    clock=clock,
                    id_generator=id_generator,
                ),
            )

            # ---- Chat front office (conversation-first P1) ---------------
            # The conversation service is CHANNEL-AGNOSTIC: built whenever the
            # front office is enabled; Slack (buttons) and Zalo (words) are
            # just transports on top of the same service instance.
            if settings.chat_front_office_enabled:
                conversation_store = SqlConversationStore(
                    session_factory=session_factory, clock=clock
                )
                conversation_service = ConversationIntakeService(
                    store=conversation_store,
                    gateway=gateway,
                    create_case=preparation.create_case,
                    rules=procurement_rules,
                    clock=clock,
                    id_generator=id_generator,
                    propose_addendum=preparation.propose_addendum,
                    submit_addendum=preparation.submit_addendum,
                    record_submission=preparation.record_submission,
                    request_cp4=preparation.request_cp4,
                    get_case=preparation.get_case,
                    list_cases=preparation.list_cases,
                    answer_clarifications=preparation.answer_clarifications,
                    run_case=preparation.run_case,
                    model_profile=settings.model_profile,
                    web_base_url=settings.public_web_url,
                )
                if settings.slack_bot_token and settings.slack_app_token:
                    chat = ChatFrontOffice(
                        app_token=settings.slack_app_token,
                        chat_client=SlackChatClient(bot_token=settings.slack_bot_token),
                        conversation_store=conversation_store,
                        conversation_service=conversation_service,
                        slack_user_reverse_map=settings.slack_user_reverse_map(),
                    )
    elif settings.profile == "production":
        settings.require_database_url()

    return ApiContainer(
        settings=settings,
        engine=engine,
        health_service=HealthService(probes={"database": database_probe(engine)}),
        token_verifier=_build_token_verifier(settings),
        access_context_factory=access_context_factory,
        identity_bootstrap=identity_bootstrap,
        uow_factory=uow_factory,
        authorization=authorization,
        entitlement=entitlement,
        run_store=run_store,
        approval_flow=approval_flow,
        work_ops=work_ops,
        tender=tender,
        preparation=preparation,
        knowledge_gateway=knowledge_gateway,
        ingest_job_store=ingest_job_store,
        object_storage=object_storage,
        memory_service=memory_service,
        tool_registry=tool_registry,
        chat=chat,
        conversation_store=conversation_store,
        conversation_service=conversation_service,
    )
