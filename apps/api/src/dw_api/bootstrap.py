"""Composition root: the only place concrete adapters are wired together.

Tests build their own container with fake ports; production wiring lives here.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

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
from dw_api.pending_authority import SqlPendingAuthority
from dw_api.settings import ApiSettings
from dw_connectors.adapters.mock_task_connector import MockTaskConnectorAdapter
from dw_connectors.adapters.slack_chat import SlackChatClient
from dw_kernel.net_guard import ensure_allowed_outbound_url
from dw_kernel.ports import IdGenerator, SystemClock, Uuid4Generator
from dw_kernel.resilience import CircuitBreaker
from dw_knowledge.adapters.websearch.contracts import WebSearchProvider
from dw_knowledge.gateway import KnowledgeGateway
from dw_knowledge.ingest_jobs import IngestJobStore
from dw_knowledge.ports import KnowledgeGatewayPort, ObjectStoragePort
from dw_memory.policy import MemoryWritePolicy
from dw_memory.service import MemoryService
from dw_observability.telemetry import NullTelemetry, TelemetryPort
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.identity.keycloak import KeycloakTokenVerifier
from dw_platform.adapters.persistence.channel_link_repository import SqlChannelLinkRepository
from dw_platform.adapters.persistence.identity_provisioning import SqlIdentityBootstrap
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.channel_link import (
    DescribeChannelLinksHandler,
    IssueChannelLinkCodeHandler,
    RedeemChannelLinkCodeHandler,
    UnlinkChannelHandler,
)
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
from dw_tender.adapters.preparation.intake_quota_rules_loader import load_intake_quota_rules
from dw_tender.adapters.preparation.repositories import SqlPreparationUnitOfWorkFactory
from dw_tender.adapters.preparation.rework_rules_loader import load_rework_support_rules
from dw_tender.adapters.preparation.rules_loader import load_procurement_rules
from dw_tender.application.conversation.service import ConversationIntakeService
from dw_tender.application.handlers import (
    AnalyzeCaseHandler,
    CreateTenderCaseHandler,
    GetTenderCaseHandler,
    ListTenderCasesHandler,
)
from dw_tender.application.preparation.amend import AmendPreparationCaseHandler
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
from dw_tender.application.preparation.handoff import HandoffToEvaluationHandler
from dw_tender.application.preparation.intake_quota_guard import IntakeQuotaGuard
from dw_tender.application.preparation.intake_quota_handlers import (
    SubmitQuotaJustificationHandler,
)
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.application.preparation.readiness import AssessTenderReadinessHandler
from dw_tender.application.preparation.rework_guard import ReworkGuard
from dw_tender.application.preparation.rework_handlers import (
    AssessReworkSupportHandler,
    DecideExplanationHandler,
    EscalateStaleExplanationsHandler,
    ListPendingExplanationsHandler,
    SubmitExplanationHandler,
    VoidReworkEventHandler,
)
from dw_tender.application.preparation.rules import ProcurementRules
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

if TYPE_CHECKING:  # imported lazily at call time to keep startup cheap
    from dw_knowledge.adapters.web_law_search import LegalSourceConfig

# In dev the repo root is derived from the source tree; in containers the
# package lives in site-packages, so the image sets DW_REPO_ROOT=/app and
# ships configs/, evals/fixtures/ and contracts/release/ at that root.
REPO_ROOT = Path(os.environ.get("DW_REPO_ROOT", str(Path(__file__).resolve().parents[4])))

logger = logging.getLogger("dw_api.bootstrap")


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
    assess_readiness: AssessTenderReadinessHandler
    amend_case: AmendPreparationCaseHandler
    handoff_to_evaluation: HandoffToEvaluationHandler
    # Needed by the bid-closing scanner (deadline-driven CP4).
    uow_factory: PreparationUnitOfWorkFactory
    rules: ProcurementRules
    rework_guard: ReworkGuard
    intake_quota_guard: IntakeQuotaGuard
    assess_rework: AssessReworkSupportHandler
    list_pending_explanations: ListPendingExplanationsHandler
    submit_explanation: SubmitExplanationHandler
    decide_explanation: DecideExplanationHandler
    void_rework_event: VoidReworkEventHandler
    escalate_explanations: EscalateStaleExplanationsHandler


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
    legal_gateway: KnowledgeGatewayPort | None = None
    model_gateway: RoutingModelGateway | None = None
    ingest_job_store: IngestJobStore | None = None
    object_storage: ObjectStoragePort | None = None
    memory_service: MemoryService | None = None
    tool_registry: ToolRegistry | None = None
    chat: ChatFrontOffice | None = None
    # Channel-agnostic chat core — shared by Slack (buttons) and Zalo (words).
    conversation_store: SqlConversationStore | None = None
    conversation_service: ConversationIntakeService | None = None
    channel_link_repository: SqlChannelLinkRepository | None = None
    issue_channel_link: IssueChannelLinkCodeHandler | None = None
    redeem_channel_link: RedeemChannelLinkCodeHandler | None = None
    unlink_channel: UnlinkChannelHandler | None = None
    describe_channel_links: DescribeChannelLinksHandler | None = None

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
    if settings.fpt_api_key and settings.fpt_base_url:
        # Second OpenAI-compatible endpoint on its own credentials (FPT Cloud,
        # GLM-5.2). Chat/completions only: that gateway answers /v1/responses
        # but returns no reasoning items, so the Responses adapter would cost
        # stricter schemas for nothing (verified 2026-08-24, see glm.yaml).
        ensure_allowed_outbound_url(
            settings.fpt_base_url,
            allow_private=settings.outbound_allow_private(),
            allowed_hosts=tuple(settings.outbound_allowed_hosts),
        )
        adapters["fpt_openai"] = OpenAICompatibleAdapter(
            base_url=settings.fpt_base_url,
            api_key=settings.fpt_api_key,
            provider="fpt_openai",
            structured_mode=settings.openai_structured_mode,
            breaker=CircuitBreaker(clock=SystemClock(), name="model.fpt_openai"),
        )
    # "A real provider is wired" is the rule; naming one key would now reject a
    # deployment that runs entirely on fpt_openai.
    if settings.profile == "production" and not (adapters.keys() - {"mock"}):
        raise RuntimeError("production requires a real model provider")
    return adapters


def _build_search_providers(
    settings: ApiSettings, config: LegalSourceConfig, names: tuple[str, ...]
) -> list[WebSearchProvider]:
    """The configured chain, in configured order, minus whoever has no key.

    Mirrors ``_build_model_adapters``: the composition root is the only place
    that knows which concrete integrations exist. A provider named in config but
    missing its secret is dropped here with a line saying so — the alternative
    is discovering it mid-run, where the caller swallows retrieval failures and
    the gap looks like "the law says nothing about this".
    """
    from dw_knowledge.adapters.websearch.providers.brave import BraveProvider
    from dw_knowledge.adapters.websearch.providers.duckduckgo import DuckDuckGoProvider
    from dw_knowledge.adapters.websearch.providers.google_cse import GoogleCseProvider
    from dw_knowledge.adapters.websearch.providers.serper import SerperProvider
    from dw_knowledge.adapters.websearch.providers.tavily import TavilyProvider

    def breaker(name: str) -> CircuitBreaker:
        return CircuitBreaker(clock=SystemClock(), name=f"knowledge.{name}")

    built: list[WebSearchProvider] = []
    for name in names:
        if name == "serper" and settings.serper_api_key:
            built.append(SerperProvider(api_key=settings.serper_api_key, breaker=breaker(name)))
        elif name == "brave" and settings.brave_api_key:
            built.append(BraveProvider(api_key=settings.brave_api_key, breaker=breaker(name)))
        elif name == "tavily" and settings.tavily_api_key:
            built.append(
                TavilyProvider(
                    api_key=settings.tavily_api_key,
                    search_depth=config.tavily_search_depth,
                    breaker=breaker(name),
                )
            )
        elif name == "google_cse" and settings.google_cse_api_key and settings.google_cse_cx:
            built.append(
                GoogleCseProvider(
                    api_key=settings.google_cse_api_key,
                    engine_id=settings.google_cse_cx,
                    breaker=breaker(name),
                )
            )
        elif name == "duckduckgo":
            # The only one needing no secret — and the only one with no service
            # commitment behind it. Enabled solely when config asks for it.
            built.append(DuckDuckGoProvider(breaker=breaker(name)))
        else:
            logger.info("web search: bỏ qua %s — chưa cấu hình khoá", name)
    return built


def _build_legal_gateway(
    settings: ApiSettings,
    corpus: KnowledgeGatewayPort,
    id_generator: IdGenerator,
) -> KnowledgeGatewayPort:
    """Choose where legal questions are answered from.

    An ingested corpus is a photograph of the law; live search is the law as it
    stands when a package is drafted. Only ``domain="legal"`` moves — company
    procurement rules are not on the web, so policy retrieval is unaffected by
    this choice.

    Misconfiguration degrades to the corpus rather than to silence: with no
    usable provider there is nothing to search, and a drafting run that quietly
    loses its legal grounding is worse than one using the indexed copy.
    """
    if settings.legal_source != "web":
        return corpus

    from dw_knowledge.adapters.web_law_search import (
        DEFAULT_ROUTING,
        LegalSourceRouter,
        PageFetcher,
        TtlCache,
        WebLawGateway,
        load_legal_sources,
    )
    from dw_knowledge.adapters.websearch.chain import FailoverSearchClient, ProviderCooldown

    config = load_legal_sources(REPO_ROOT / "configs" / "knowledge" / "legal_sources@1.1.0.yaml")
    if not config.allowed_domains:
        # The allowlist is the fence. Without it every SEO farm is a legal
        # source, so an empty list means the feature stays off.
        logger.warning("legal source allowlist is empty — using the corpus")
        return corpus

    providers = _build_search_providers(settings, config, config.providers or ("serper",))
    if not providers:
        logger.warning("DW_LEGAL_SOURCE=web nhưng không provider nào có khoá — dùng corpus")
        return corpus

    web = WebLawGateway(
        client=FailoverSearchClient(
            providers=providers,
            cooldown=ProviderCooldown(default_seconds=config.exhausted_cooldown_seconds),
            advance_on_empty=config.advance_on_empty,
        ),
        fetcher=PageFetcher(
            policy=config.fetch_policy, allow_private=settings.outbound_allow_private()
        ),
        config=config,
        id_generator=id_generator,
        cache=TtlCache(config.cache_ttl_seconds, config.cache_max_entries),
    )
    logger.info(
        "legal retrieval via web search (chuỗi: %s | %d nguồn tin cậy | config %s)",
        " → ".join(p.provider_name for p in providers),
        len(config.allowed_domains),
        config.version,
    )
    return LegalSourceRouter(
        inner=corpus,
        web=web,
        routing=config.routing or DEFAULT_ROUTING,
        corpus_fallback=config.corpus_fallback,
    )


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
    legal_gateway: KnowledgeGatewayPort | None = None
    model_gateway: RoutingModelGateway | None = None
    ingest_job_store: IngestJobStore | None = None
    object_storage: ObjectStoragePort | None = None
    memory_service: MemoryService | None = None
    tool_registry: ToolRegistry | None = None
    chat: ChatFrontOffice | None = None
    conversation_store: SqlConversationStore | None = None
    conversation_service: ConversationIntakeService | None = None
    channel_link_repository: SqlChannelLinkRepository | None = None
    issue_channel_link: IssueChannelLinkCodeHandler | None = None
    redeem_channel_link: RedeemChannelLinkCodeHandler | None = None
    unlink_channel: UnlinkChannelHandler | None = None
    describe_channel_links: DescribeChannelLinksHandler | None = None

    if settings.database_url:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        access_context_factory = DbAccessContextFactory(SqlMembershipLookup(session_factory))
        # Self-service chat linking: the web side mints a code for a signed-in
        # person, the chat side quotes it back. Replaces the hand-kept id map.
        channel_link_repository = SqlChannelLinkRepository(session_factory)
        issue_channel_link = IssueChannelLinkCodeHandler(
            repository=channel_link_repository,
            clock=clock,
            id_generator=id_generator,
            ttl=timedelta(minutes=settings.channel_link_ttl_minutes),
        )
        redeem_channel_link = RedeemChannelLinkCodeHandler(
            repository=channel_link_repository, clock=clock
        )
        unlink_channel = UnlinkChannelHandler(repository=channel_link_repository)
        describe_channel_links = DescribeChannelLinksHandler(repository=channel_link_repository)
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
                    client=AsyncQdrantClient(url=settings.qdrant_url),
                    collection=settings.qdrant_collection,
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
            legal_gateway = _build_legal_gateway(settings, knowledge_gateway, id_generator)
            model_gateway = gateway
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
            rework_rules = load_rework_support_rules(
                REPO_ROOT / "configs" / "policies" / "dw01" / "rework_support_v1.yaml"
            )
            rework_guard = ReworkGuard(
                uow_factory=preparation_uow_factory,
                rules=rework_rules,
                clock=clock,
            )
            intake_quota_guard = IntakeQuotaGuard(
                uow_factory=preparation_uow_factory,
                rules=load_intake_quota_rules(
                    REPO_ROOT / "configs" / "policies" / "dw01" / "intake_quota_v1.yaml"
                ),
                clock=clock,
            )
            preparation_services = PreparationServices(
                uow_factory=preparation_uow_factory,
                storage=storage,  # type: ignore[arg-type]
                rules=procurement_rules,
                # Supplier candidates are case input, never a hidden fixture.
                suppliers=(),
                clock=clock,
                id_generator=id_generator,
                knowledge=legal_gateway,
                model_gateway=gateway,
                model_profile=settings.model_profile,
                autonomy_profile=settings.autonomy_profile,
                rework_rules=rework_rules,
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
                    rework_guard=rework_guard,
                    intake_quota_guard=intake_quota_guard,
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
                    rework_guard=rework_guard,
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
                    rework_rules=rework_rules,
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
                    rules=procurement_rules,
                ),
                request_cp4=RequestCp4Handler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    clock=clock,
                    id_generator=id_generator,
                    rules=procurement_rules,
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
                    storage=storage,  # type: ignore[arg-type]
                    email_publisher=_build_email_publisher(),  # type: ignore[arg-type]
                    recipient_email=os.environ.get("DW_PUBLICATION_EMAIL", "")
                    or os.environ.get("SMTP_USER", ""),
                ),
                uow_factory=preparation_uow_factory,
                rules=procurement_rules,
                audit_recorder=PreparationAuditRecorder(
                    uow_factory=uow_factory,
                    clock=clock,
                    id_generator=id_generator,
                ),
                amend_case=AmendPreparationCaseHandler(
                    uow_factory=preparation_uow_factory,
                    platform_uow_factory=uow_factory,
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
                handoff_to_evaluation=HandoffToEvaluationHandler(
                    uow_factory=preparation_uow_factory,
                    storage=storage,  # type: ignore[arg-type]
                    authorization=authorization,
                    id_generator=id_generator,
                    create_evaluation_case=tender.create_case,
                    analyze_case=tender.analyze_case,
                ),
                assess_readiness=AssessTenderReadinessHandler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    rules=procurement_rules,
                    id_generator=id_generator,
                    gateway=gateway,
                    model_profile=settings.model_profile,
                ),
                rework_guard=rework_guard,
                intake_quota_guard=intake_quota_guard,
                assess_rework=AssessReworkSupportHandler(guard=rework_guard),
                list_pending_explanations=ListPendingExplanationsHandler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    guard=rework_guard,
                ),
                submit_explanation=SubmitExplanationHandler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    guard=rework_guard,
                    clock=clock,
                    id_generator=id_generator,
                ),
                decide_explanation=DecideExplanationHandler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    guard=rework_guard,
                    clock=clock,
                ),
                void_rework_event=VoidReworkEventHandler(
                    uow_factory=preparation_uow_factory,
                    authorization=authorization,
                    clock=clock,
                ),
                escalate_explanations=EscalateStaleExplanationsHandler(
                    uow_factory=preparation_uow_factory,
                    guard=rework_guard,
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
                    rework_guard=rework_guard,
                    intake_quota_guard=intake_quota_guard,
                    submit_quota_justification=SubmitQuotaJustificationHandler(
                        uow_factory=preparation_uow_factory,
                        authorization=authorization,
                        guard=intake_quota_guard,
                        clock=clock,
                        id_generator=id_generator,
                    ),
                    rules=procurement_rules,
                    clock=clock,
                    id_generator=id_generator,
                    propose_addendum=preparation.propose_addendum,
                    submit_addendum=preparation.submit_addendum,
                    record_submission=preparation.record_submission,
                    request_cp4=preparation.request_cp4,
                    get_case=preparation.get_case,
                    list_cases=preparation.list_cases,
                    pending_authority=SqlPendingAuthority(
                        uow_factory=uow_factory, session_factory=session_factory
                    ),
                    # The router, not the raw corpus: a colleague asking "how
                    # many days must we give bidders?" should get today's law,
                    # the same as the drafting run does.
                    knowledge=legal_gateway,
                    assess_readiness=preparation.assess_readiness,
                    amend_case=preparation.amend_case,
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
        channel_link_repository=channel_link_repository,
        issue_channel_link=issue_channel_link,
        redeem_channel_link=redeem_channel_link,
        unlink_channel=unlink_channel,
        describe_channel_links=describe_channel_links,
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
        legal_gateway=legal_gateway,
        model_gateway=model_gateway,
        ingest_job_store=ingest_job_store,
        object_storage=object_storage,
        memory_service=memory_service,
        tool_registry=tool_registry,
        chat=chat,
        conversation_store=conversation_store,
        conversation_service=conversation_service,
    )
