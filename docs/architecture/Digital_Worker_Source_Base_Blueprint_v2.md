---
title: "Digital Worker Platform - Source Base Architecture Blueprint"
subtitle: "DW Đấu thầu và DW Điều hành công việc"
author: "Architecture specification for source-base generation"
date: "23/07/2026"
version: "2.0.0"
lang: vi-VN
---

# 1. Mục đích tài liệu

Tài liệu này là **đặc tả kiến trúc và hợp đồng triển khai** để Claude Code tạo source base ban đầu cho nền tảng Digital Worker. Source base phải nhỏ đủ để dựng POC nhanh, nhưng có cấu trúc đủ chuẩn để tiếp tục phát triển thành sản phẩm enterprise mà không phải viết lại toàn bộ.

Nền tảng phục vụ hai Digital Worker đầu tiên:

1. **Procurement Tender Digital Worker**: hỗ trợ quy trình đề xuất mua hàng, RFQ/hồ sơ mời thầu, trích xuất yêu cầu, đánh giá nhà cung cấp, phát hiện rủi ro và chuẩn bị đề xuất để con người phê duyệt.
2. **Executive Work Coordination Digital Worker**: nhận transcript/meeting note, tóm tắt, trích xuất quyết định và action item, xác định người/phòng ban, tạo nội dung giao việc, gửi qua Slack/Teams/Planner/Jira và theo dõi tiến độ.

Tài liệu không chỉ mô tả “dùng framework nào”, mà quy định:

- Cách chia module và dependency.
- Các pattern bắt buộc và vị trí sử dụng.
- Cấu trúc monorepo và từng package.
- Hợp đồng API, event, tool, memory và workflow.
- Multi-tenant, phân quyền, entitlement và data isolation.
- Versioning toàn bộ code và non-code artifacts.
- CI/CD, testing, evaluation, observability và security.
- Trình tự Claude Code phải tạo source và tiêu chí nghiệm thu.

> Kết quả mong muốn không phải một chatbot demo. Kết quả là một **production-shaped source base** có một vertical slice chạy được end-to-end, có boundary, trace, test, approval và khả năng thay adapter.

# 2. Quyết định kiến trúc tổng thể

## 2.1 Một nền tảng, hai bounded context

Xây dựng:

- **Một monorepo**.
- **Một UI shell dùng chung**.
- **Một shared platform/runtime**.
- **Hai bounded context nghiệp vụ độc lập**.
- **Hai agentic workflow độc lập**.
- **Không tạo một “siêu-agent” có tất cả dữ liệu và công cụ**.

Hai bounded context được phép chia sẻ các capability nền tảng như authentication, tenant context, model gateway, memory service, knowledge gateway, approval, audit và connector gateway. Chúng không được import trực tiếp entity, repository hoặc use case của nhau.

Giao tiếp giữa hai bounded context chỉ qua:

- Public application contract.
- Versioned domain/integration event.
- Shared kernel rất nhỏ, không chứa business logic.

## 2.2 Modular monolith trước, microservice-ready sau

POC triển khai dưới dạng **modular monolith + asynchronous worker process**:

- Một API process.
- Một hoặc nhiều worker process.
- Một web application.
- Các module Python độc lập trong uv workspace.

Chỉ tách thành microservice khi xuất hiện ít nhất một trong các điều kiện:

- Cần scale tải độc lập.
- Có yêu cầu compliance hoặc network isolation khác nhau.
- Có team ownership và release cadence độc lập.
- Failure của một module không được ảnh hưởng module khác.
- Hạ tầng hoặc dependency xung đột.

Việc tách sau này phải thực hiện bằng cách thay adapter/transport, không viết lại domain và application layer.

## 2.3 Single-agent workflow cho mỗi Digital Worker

Trong POC:

- Một `TenderAgent` cho DW Đấu thầu.
- Một `WorkOpsAgent` cho DW Điều hành công việc.
- Mỗi agent gồm nhiều node chuyên biệt trong state graph.
- Chưa tách mỗi node thành một agent riêng.

Multi-agent chỉ được thêm khi có nhiều role thật sự độc lập, mỗi role có goal, memory, tool, quyền và KPI riêng.

## 2.4 Human-in-command

AI được giao đọc hiểu, truy xuất, suy luận, tạo structured output và chuẩn bị hành động. Code và workflow engine giữ quyền kiểm soát:

- Authorization.
- Validation.
- Transaction.
- Idempotency.
- Approval.
- Side effect.
- Audit.
- Rollback.

Mọi quyết định consequence cao phải có approval hoặc policy gate. Digital Worker không tự thay đổi goal, policy, quyền hạn hoặc approval threshold.

# 3. Mục tiêu và phạm vi source base

## 3.1 Mục tiêu bắt buộc

Source base phải chứng minh được:

- Chạy local bằng một lệnh hoặc một chuỗi lệnh ngắn.
- Có login mock hoặc OIDC-ready.
- Có ít nhất hai tenant và kiểm thử không rò dữ liệu chéo tenant.
- Có một UI shell với hai module nghiệp vụ.
- Có một workflow meeting-to-action chạy end-to-end.
- Có một workflow tender-analysis chạy end-to-end với dữ liệu mẫu.
- Có human approval trước side effect.
- Có adapter mock cho Slack/Teams và adapter thật tối thiểu cho một nền tảng test nếu có credential.
- Có PostgreSQL, Qdrant, object storage và Redis/Valkey trong Docker Compose.
- Có structured logging, OpenTelemetry trace và Langfuse integration có thể bật/tắt.
- Có unit test, integration test, contract test, architecture test và eval regression tối thiểu.
- Có version cho worker, graph, prompt, tool, policy và event schema.
- Có tài liệu ADR, runbook và threat model tối thiểu.

## 3.2 Không nằm trong source base đầu tiên

Không cần hoàn thiện:

- Bot tự tham gia cuộc họp trực tiếp.
- Full production connector cho ERP/SAP/Teams/Planner/Jira.
- Full multi-agent orchestration.
- Tự động duyệt nhà cung cấp hoặc phát hành PO.
- Kubernetes production hoàn chỉnh.
- Graph database riêng.
- Billing thực tế.
- Fine-tuning model.

Tuy nhiên source phải có port/adapter boundary để thêm các phần trên mà không phá domain.

# 4. Kiến trúc ứng dụng

![Kiến trúc tổng thể](dw_source_blueprint_assets/architecture_overview.png)

## 4.1 Experience Plane

Các kênh tương tác:

- Web application.
- Slack app.
- Microsoft Teams app.
- REST API, webhook và file upload.

Kênh chỉ làm nhiệm vụ nhận/gửi message, render state, hiển thị evidence và approval. Kênh không chứa business rule hoặc trực tiếp gọi provider SDK.

## 4.2 Control Plane

Capability dùng chung:

- Identity, tenant và workspace context.
- Subscription plan và entitlement.
- Worker registry.
- Tool registry.
- Connector registry.
- Model gateway và model routing.
- Policy decision và approval.
- Agent runtime, checkpoint và resume.
- Audit, evaluation và AgentOps.

## 4.3 Domain Plane

### Tender bounded context

Quản lý:

- Tender case.
- Procurement request.
- Requirement.
- Supplier submission.
- Evaluation criterion.
- Compliance finding.
- Recommendation.
- Approval decision.

### Work Operations bounded context

Quản lý:

- Meeting session.
- Transcript artifact.
- Decision record.
- Action item.
- Assignee resolution.
- Dispatch request.
- External task link.
- Follow-up và escalation.

## 4.4 Data Plane

- PostgreSQL: system of record, workflow metadata, tenant, ACL, audit và graph entity/relation.
- Qdrant: dense/sparse vectors, hybrid retrieval và long-term semantic memory.
- S3/MinIO: tài liệu gốc, transcript, evidence và exports.
- Redis/Valkey: cache, distributed lock, rate-limit và queue nhẹ; không là nguồn dữ liệu có thẩm quyền.
- OpenTelemetry/Langfuse: traces, model calls, retrieval, tool calls, cost và evaluation.

# 5. Lựa chọn UI

## 5.1 Lựa chọn khuyến nghị

**Next.js + TypeScript + Tailwind CSS + shadcn/ui + CopilotKit**.

Lý do:

- UI của dự án không chỉ là chat; cần dashboard, approval inbox, evidence viewer, run timeline và admin.
- CopilotKit có integration trực tiếp với LangGraph/Python, hỗ trợ shared state, generative UI và human-in-the-loop.
- MIT license và có thể nhúng vào product shell.
- Có thể thay từng thành phần UI mà không phụ thuộc một ứng dụng chat hoàn chỉnh.

CopilotKit chỉ là adapter UX. Domain và agent runtime không được phụ thuộc trực tiếp vào package frontend này.

## 5.2 Lựa chọn thay thế

**assistant-ui** phù hợp khi cần bộ primitives chat thấp hơn, muốn tự quản protocol và render hoàn toàn theo thiết kế nội bộ. Có thể dùng nếu team không muốn CopilotKit runtime.

## 5.3 Không chọn Open WebUI làm product shell chính

Open WebUI phù hợp làm internal sandbox hoặc model playground, nhưng không nên là UI chính vì:

- Thiên về sản phẩm chat độc lập hơn là domain application.
- Khó áp dụng sâu bounded context, approval workspace và custom domain navigation.
- Plugin/function có thể chạy Python với quyền mạnh, cần governance riêng.
- License hiện tại có điều khoản bảo vệ branding, đặc biệt khi thay branding cho deployment trên 50 end users.

## 5.4 Route và feature layout

```text
/
├── /home
├── /inbox
├── /approvals
├── /procurement
│   ├── /cases
│   ├── /cases/[caseId]
│   ├── /suppliers
│   └── /evaluations
├── /work-ops
│   ├── /meetings
│   ├── /meetings/[meetingId]
│   ├── /actions
│   └── /follow-ups
├── /knowledge
├── /memory
├── /integrations
├── /audit
└── /admin
```

## 5.5 UI patterns

- Feature-first folders.
- Server state do TanStack Query hoặc framework-native data cache quản lý.
- Form validation dùng Zod.
- API client được generate từ OpenAPI, không tự viết type trùng lặp.
- Component domain không gọi trực tiếp Slack/Teams/LLM.
- Tool call và agent state render qua typed UI registry.
- Approval component nhận `ApprovalRequest` schema, không nhận arbitrary model output.
- Chat là một surface; mọi kết quả quan trọng phải có domain view riêng.

# 6. Backend stack

## 6.1 Stack chính

| Hạng mục                    | Lựa chọn                                                      |
| --------------------------- | ------------------------------------------------------------- |
| Runtime                     | Python 3.12                                                   |
| Package/workspace           | uv workspace + một lockfile                                   |
| API                         | FastAPI                                                       |
| Validation/DTO              | Pydantic v2                                                   |
| ORM                         | SQLAlchemy 2 async                                            |
| Migration                   | Alembic                                                       |
| Agent workflow              | LangGraph                                                     |
| Durable long-running option | Temporal adapter, thêm sau qua port                           |
| Database                    | PostgreSQL                                                    |
| Vector/hybrid               | Qdrant                                                        |
| Object storage              | S3/MinIO                                                      |
| Cache/lock                  | Redis hoặc Valkey                                             |
| Auth                        | OIDC, local Keycloak cho POC                                  |
| Policy                      | Internal policy adapter; Cerbos adapter cho enterprise        |
| Telemetry                   | OpenTelemetry                                                 |
| LLM observability/eval      | Langfuse self-host hoặc cloud                                 |
| Testing                     | pytest, pytest-asyncio, HTTPX, Testcontainers/Docker services |
| Quality                     | Ruff, mypy/pyright, import-linter, pre-commit                 |

## 6.2 Nguyên tắc pin dependency

- Không ghi `latest` trong manifest production.
- Claude Code phải resolve bản stable tương thích tại thời điểm bootstrap và commit lockfile.
- Python dependencies pin trong `uv.lock`.
- Node dependencies pin trong `pnpm-lock.yaml`.
- Docker images pin major/minor hoặc digest ở CI/staging.
- Mỗi upgrade dependency phải chạy test, eval regression và smoke test.

# 7. Kiến trúc source code và dependency rule

![Dependency rule](dw_source_blueprint_assets/dependency_rule.png)

## 7.1 Clean/Hexagonal Architecture

Mỗi bounded context có bốn lớp:

1. **Domain**: entity, value object, invariant, domain service, domain event.
2. **Application**: use case, command/query, port, transaction boundary.
3. **Adapters/Infrastructure**: database, vector store, LLM, connector, filesystem, policy engine.
4. **Presentation**: API route, webhook handler, CLI, queue consumer.

Dependency luôn hướng vào trong:

```text
presentation ──> application ──> domain
adapters ──────> application ports
composition root ──> tất cả để wiring
```

Domain layer:

- Chỉ dùng standard library khi có thể.
- Không import FastAPI, SQLAlchemy, LangGraph, Qdrant, Slack SDK hoặc provider LLM.
- Không biết tenant được lấy từ HTTP header thế nào.
- Không biết dữ liệu được lưu ở database nào.

## 7.2 DDD bounded context

Tên và model của Tender không được dùng chung tùy tiện với Work Operations. Shared kernel chỉ chứa các primitive thực sự phổ quát:

- `TenantId`, `WorkspaceId`, `UserId`.
- `EntityId`.
- `Money` nếu cần.
- `UtcClock` port.
- Base domain event.
- Page/cursor primitives.

Không đưa `User`, `Document`, `Task` dạng generic quá lớn vào shared kernel.

## 7.3 Ports and Adapters

Mọi external dependency được bọc bằng port:

```python
from typing import Protocol

class ModelGateway(Protocol):
    async def generate_structured(
        self,
        request: "ModelRequest",
        output_type: type["OutputT"],
    ) -> "OutputT": ...

class VectorSearchPort(Protocol):
    async def search(
        self,
        query: "SearchQuery",
        context: "AccessContext",
    ) -> list["EvidenceChunk"]: ...

class TaskConnectorPort(Protocol):
    async def create_task(
        self,
        command: "CreateExternalTask",
        idempotency_key: str,
    ) -> "ExternalTaskRef": ...
```

Adapter ví dụ:

- `OpenAIModelAdapter`.
- `AzureOpenAIModelAdapter`.
- `VLLMModelAdapter`.
- `QdrantVectorSearchAdapter`.
- `SlackTaskConnectorAdapter`.
- `TeamsPlannerConnectorAdapter`.
- `MockTaskConnectorAdapter`.

## 7.4 Repository và Unit of Work

Repository chỉ thao tác aggregate. Use case không gọi SQLAlchemy session trực tiếp.

```python
class MeetingRepository(Protocol):
    async def get(self, meeting_id: MeetingId) -> MeetingSession | None: ...
    async def add(self, meeting: MeetingSession) -> None: ...

class UnitOfWork(Protocol):
    meetings: MeetingRepository
    actions: ActionItemRepository

    async def __aenter__(self) -> "UnitOfWork": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
```

Mỗi request hoặc command có một transaction boundary rõ ràng. Không share `AsyncSession` giữa concurrent tasks.

## 7.5 Command, Query và Application Service

- Command thay đổi state.
- Query chỉ đọc.
- Use case orchestration nằm ở application layer.
- Không đưa orchestration nghiệp vụ vào API route.

Ví dụ:

```python
@dataclass(frozen=True)
class GenerateMeetingActionsCommand:
    tenant_id: TenantId
    meeting_id: MeetingId
    requested_by: UserId
    worker_version: str

class GenerateMeetingActionsHandler:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workflow_runner: WorkflowRunnerPort,
        authorization: AuthorizationPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._workflow_runner = workflow_runner
        self._authorization = authorization

    async def handle(self, cmd: GenerateMeetingActionsCommand) -> RunId:
        await self._authorization.require(
            principal=cmd.requested_by,
            action="meeting.generate_actions",
            resource_id=str(cmd.meeting_id),
            tenant_id=cmd.tenant_id,
        )
        return await self._workflow_runner.start(
            worker_id="work_ops",
            worker_version=cmd.worker_version,
            input={"meeting_id": str(cmd.meeting_id)},
            tenant_id=cmd.tenant_id,
        )
```

## 7.6 Strategy, Factory và Registry

Dùng Strategy cho:

- Model routing.
- Embedding provider.
- Retrieval strategy.
- Reranking strategy.
- Memory write policy.
- Cost profile.

Dùng Factory/Registry cho:

- Worker definition.
- Workflow graph version.
- Tool implementation.
- Connector implementation.
- Provider adapter.

Registry phải typed và fail-fast khi config tham chiếu implementation không tồn tại.

## 7.7 Anti-Corruption Layer

Mỗi external system có model riêng. Adapter phải map external DTO sang canonical internal contract.

Ví dụ Slack `user_id`, Teams `aadObjectId` và hệ thống HR `employee_code` đều được map thành `OrganizationPersonRef`. Domain không lưu raw provider response làm entity chính.

## 7.8 Outbox Pattern

Mọi side effect sau transaction sử dụng outbox:

1. Use case thay đổi aggregate.
2. Ghi domain/integration event vào bảng `outbox_events` trong cùng transaction.
3. Worker publish hoặc thực thi side effect.
4. Đánh dấu processed với idempotency.

Không gọi Slack/Teams trước khi database commit thành công.

## 7.9 Specification và Policy

Rule có thể kết hợp nên dùng specification/policy object:

```python
class CanAutoDispatchAction:
    def evaluate(self, action: ActionItem, ctx: PolicyContext) -> PolicyDecision:
        if action.risk_level != RiskLevel.LOW:
            return PolicyDecision.require_approval("risk_not_low")
        if action.department_id != ctx.requester_department_id:
            return PolicyDecision.require_approval("cross_department")
        if action.confidence < ctx.min_auto_dispatch_confidence:
            return PolicyDecision.require_approval("low_confidence")
        return PolicyDecision.allow()
```

## 7.10 Resilience patterns

External calls phải có:

- Timeout.
- Retry có exponential backoff và jitter cho lỗi transient.
- Circuit breaker ở connector/model gateway khi phù hợp.
- Bulkhead/concurrency limit theo tenant/provider.
- Idempotency key cho side effect.
- Dead-letter/failed job state.
- Compensation hoặc action preview đối với giao dịch quan trọng.

# 8. Cấu trúc monorepo chuẩn

```text
digital-worker-platform/
├── README.md
├── CLAUDE.md
├── CHANGELOG.md
├── LICENSE
├── Makefile
├── Taskfile.yml
├── pyproject.toml
├── uv.lock
├── package.json
├── pnpm-workspace.yaml
├── pnpm-lock.yaml
├── turbo.json
├── .env.example
├── .editorconfig
├── .gitignore
├── .pre-commit-config.yaml
├── .github/
│   ├── CODEOWNERS
│   ├── pull_request_template.md
│   └── workflows/
│       ├── ci.yml
│       ├── eval-regression.yml
│       ├── security.yml
│       └── release.yml
├── apps/
│   ├── api/
│   │   ├── pyproject.toml
│   │   └── src/dw_api/
│   │       ├── main.py
│   │       ├── bootstrap.py
│   │       ├── lifespan.py
│   │       ├── middleware/
│   │       ├── dependencies/
│   │       ├── exception_handlers.py
│   │       └── routes/v1/
│   ├── worker/
│   │   ├── pyproject.toml
│   │   └── src/dw_worker/
│   │       ├── main.py
│   │       ├── consumers/
│   │       ├── schedulers/
│   │       └── health.py
│   └── web/
│       ├── app/
│       ├── components/
│       ├── features/
│       ├── lib/
│       ├── public/
│       └── tests/
├── packages/
│   ├── python/
│   │   ├── dw_kernel/
│   │   ├── dw_platform/
│   │   ├── dw_agent_runtime/
│   │   ├── dw_knowledge/
│   │   ├── dw_memory/
│   │   ├── dw_connectors/
│   │   ├── dw_tender/
│   │   ├── dw_work_ops/
│   │   ├── dw_observability/
│   │   └── dw_evals/
│   └── typescript/
│       ├── ui/
│       ├── api-client/
│       ├── contracts/
│       └── agent-ui/
├── configs/
│   ├── workers/
│   ├── prompts/
│   ├── tools/
│   ├── models/
│   ├── plans/
│   └── policies/
├── contracts/
│   ├── openapi/
│   ├── events/
│   ├── tools/
│   └── jsonschema/
├── db/
│   ├── migrations/
│   ├── rls/
│   ├── seeds/
│   └── fixtures/
├── evals/
│   ├── datasets/
│   ├── expected/
│   ├── graders/
│   └── reports/
├── infra/
│   ├── compose/
│   ├── docker/
│   ├── helm/
│   └── terraform/
├── scripts/
│   ├── bootstrap.sh
│   ├── generate_client.sh
│   ├── seed_demo.py
│   ├── run_evals.py
│   └── verify_architecture.py
└── docs/
    ├── architecture/
    ├── adr/
    ├── api/
    ├── runbooks/
    ├── threat-model/
    └── development/
```

## 8.1 Python workspace

Root `pyproject.toml` quản lý uv workspace. Mỗi app/package có `pyproject.toml` riêng và explicit dependency.

Không để package “ăn ké” dependency của package khác. CI phải chạy script kiểm tra declared dependency và import boundary.

## 8.2 Package nội bộ

### `dw_kernel`

- ID/value objects.
- Base domain event.
- Clock/UUID ports.
- Errors và result primitives.
- Không chứa framework.

### `dw_platform`

- Tenant, workspace, membership, plan, entitlement.
- Authorization contract.
- Approval, audit và outbox application services.
- Shared platform database mappings/adapters.

### `dw_agent_runtime`

- Worker definition contract.
- Workflow runner port.
- LangGraph adapter.
- Checkpoint adapter.
- Interrupt/approval mapping.
- Node execution middleware.
- Model/tool call context.

### `dw_knowledge`

- Document ingestion.
- Chunking and metadata.
- Graph entities/relations.
- Retrieval gateway.
- Qdrant and PostgreSQL graph adapters.
- Citation/evidence pack.

### `dw_memory`

- Memory item model.
- Memory read/write policy.
- Compaction/summarization.
- Retention/deletion.
- Postgres/Qdrant adapters.

### `dw_connectors`

- Canonical connector contracts.
- Slack, Teams, Planner, Jira, email adapters.
- Mock adapters.
- Credential reference và webhook verification.

### `dw_tender`

- Tender domain/application/adapters/presentation.
- Tender workflow graph and evals.

### `dw_work_ops`

- Meeting/action domain/application/adapters/presentation.
- Work operations workflow graph and evals.

### `dw_observability`

- OTel instrumentation.
- Structured logging.
- Langfuse adapter.
- Metric names and redaction.

### `dw_evals`

- Dataset schema.
- Deterministic graders.
- LLM judge adapter.
- Regression runner.
- Report generator.

# 9. Cấu trúc bên trong một bounded context

```text
dw_work_ops/src/dw_work_ops/
├── domain/
│   ├── entities/
│   ├── value_objects/
│   ├── events/
│   ├── services/
│   ├── policies/
│   └── exceptions.py
├── application/
│   ├── commands/
│   ├── queries/
│   ├── handlers/
│   ├── dto/
│   ├── ports/
│   └── mappers/
├── workflows/
│   ├── v1/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── nodes/
│   │   └── routing.py
│   └── registry.py
├── adapters/
│   ├── persistence/
│   ├── transcript/
│   ├── organization/
│   └── dispatch/
├── presentation/
│   ├── api/
│   └── events/
└── tests/
    ├── unit/
    ├── integration/
    ├── contract/
    └── eval/
```

Quy tắc:

- Workflow node gọi application service/port; không nhét SQL hoặc provider SDK vào node.
- `graph.py` chỉ định nghĩa state machine và route.
- `state.py` là typed state, có schema version.
- Mỗi node nhỏ, deterministic càng nhiều càng tốt.
- LLM output luôn parse vào Pydantic schema.
- Không truyền arbitrary dict xuyên toàn graph nếu có thể tạo type.

# 10. Agent runtime contract

## 10.1 Worker definition

```python
class WorkerDefinition(BaseModel):
    worker_id: str
    worker_version: str
    domain: Literal["tender", "work_ops"]
    graph_version: str
    prompt_bundle_version: str
    toolset_version: str
    policy_version: str
    memory_policy_version: str
    default_model_profile: str
    supported_channels: set[str]
    autonomy_level: Literal["A0", "A1", "A2", "A3", "A4"]
```

Worker definition là immutable artifact. Thay prompt/tool/graph phải tạo version mới hoặc release manifest mới.

## 10.2 Run context

```python
class RunContext(BaseModel):
    run_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    actor_id: UUID
    worker_id: str
    worker_version: str
    channel: str
    plan_id: str
    roles: set[str]
    scopes: set[str]
    trace_id: str
    locale: str = "vi-VN"
```

`RunContext` được tạo ở boundary và truyền explicit. Không lấy tenant/user từ global variable trong domain/application.

## 10.3 Tool definition

```python
class ToolDefinition(BaseModel):
    name: str
    version: str
    description: str
    input_schema_ref: str
    output_schema_ref: str
    required_scopes: set[str]
    side_effect_level: Literal["none", "internal", "external", "critical"]
    approval_policy: Literal["never", "conditional", "always"]
    timeout_seconds: int
    max_retries: int
    idempotent: bool
    data_classification: set[str]
```

Tool executor phải:

1. Resolve tool theo `(name, version)`.
2. Validate input.
3. Check authorization/policy.
4. Mask sensitive telemetry.
5. Execute với timeout/retry.
6. Validate output.
7. Ghi audit event.
8. Trả typed result.

## 10.4 Node execution middleware

Mỗi node được bọc bởi middleware:

- Trace span.
- Timeout.
- Retry policy.
- Tenant context validation.
- Cost accounting.
- Input/output redaction.
- Node version metadata.
- Error taxonomy.

# 11. Workflow DW Điều hành công việc

## 11.1 State graph

```text
INGEST_TRANSCRIPT
  → NORMALIZE_TRANSCRIPT
  → RESOLVE_SPEAKERS
  → SUMMARIZE_MEETING
  → EXTRACT_DECISIONS
  → EXTRACT_ACTION_ITEMS
  → RESOLVE_ASSIGNEES
  → VALIDATE_DUE_DATES
  → ENRICH_WITH_ORG_AND_PROJECT_CONTEXT
  → POLICY_GATE
  → HUMAN_REVIEW
  → DISPATCH_TASKS
  → TRACK_AND_FOLLOW_UP
  → CLOSE_AND_WRITE_MEMORY
```

## 11.2 State schema tối thiểu

```python
class WorkOpsState(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    meeting_id: UUID
    transcript_artifact_id: UUID
    normalized_segments: list[TranscriptSegment] = []
    summary: MeetingSummary | None = None
    decisions: list[DecisionRecord] = []
    action_candidates: list[ActionItemCandidate] = []
    resolved_actions: list[ResolvedActionItem] = []
    approval_request_id: UUID | None = None
    dispatch_results: list[DispatchResult] = []
    evidence_refs: list[EvidenceRef] = []
    warnings: list[WorkflowWarning] = []
```

## 11.3 Approval logic

Bắt buộc approval khi:

- Cross-department task.
- Assignee resolution không chắc chắn.
- Deadline do model suy đoán thay vì được nói rõ.
- Task ảnh hưởng executive commitment, khách hàng, budget hoặc nhân sự.
- Confidence dưới threshold.
- Tool side effect level là `critical`.

POC mặc định A2: chuẩn bị action và chờ người dùng xác nhận trước dispatch.

## 11.4 Connector behavior

- POC có `MockTaskConnector` luôn chạy local.
- Một connector thật có thể bật qua feature flag.
- Mapping user external phải nằm trong integration table, không để model tự tạo ID.
- Dispatch dùng idempotency key: `tenant_id:action_id:connector:version`.
- Retry không được tạo task trùng.

# 12. Workflow DW Đấu thầu

## 12.1 State graph

```text
INTAKE_CASE
  → PARSE_DOCUMENTS
  → CLASSIFY_DOCUMENTS
  → EXTRACT_REQUIREMENTS
  → BUILD_REQUIREMENT_MATRIX
  → RETRIEVE_POLICIES_AND_HISTORY
  → EXTRACT_SUPPLIER_RESPONSES
  → SCORE_COMPLIANCE
  → IDENTIFY_GAPS_AND_RISKS
  → DRAFT_RECOMMENDATION
  → DETERMINISTIC_COMPLIANCE_GATE
  → HUMAN_REVIEW
  → EXPORT_EVALUATION_PACK
  → CLOSE_AND_WRITE_MEMORY
```

## 12.2 Nguyên tắc scoring

- LLM có thể trích xuất evidence và đề xuất score.
- Công thức weight, mandatory criteria và threshold phải nằm trong deterministic code/config.
- Recommendation phải kèm evidence source và confidence.
- Không kết luận đạt mandatory criterion nếu thiếu evidence.
- Human approver là người phê duyệt shortlist/kết quả.

## 12.3 State schema tối thiểu

```python
class TenderState(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: UUID
    document_ids: list[UUID]
    requirements: list[Requirement] = []
    supplier_submissions: list[SupplierSubmission] = []
    evidence_pack: list[EvidenceRef] = []
    compliance_matrix: ComplianceMatrix | None = None
    risks: list[RiskFinding] = []
    recommendation: TenderRecommendation | None = None
    approval_request_id: UUID | None = None
```

# 13. Knowledge, RAG và GraphRAG

## 13.1 Qdrant không phải toàn bộ graph

POC dùng:

- Qdrant cho dense/sparse vectors và filtered retrieval.
- PostgreSQL cho entity/relation tables và traversal cơ bản.
- Object storage cho source artifact.

Chỉ thêm Neo4j/graph database khi cần traversal sâu, ontology phức tạp hoặc graph algorithms mà PostgreSQL không còn phù hợp.

## 13.2 Retrieval pipeline

```text
Request + AccessContext
  → Query classification
  → Mandatory tenant/workspace/ACL filter
  → Dense + sparse retrieval
  → Metadata constraint
  → Rerank
  → Entity/relation expansion
  → Evidence deduplication
  → Evidence pack with provenance
  → Agent node
```

## 13.3 Metadata bắt buộc trong Qdrant

```json
{
    "tenant_id": "uuid",
    "workspace_id": "uuid",
    "domain": "tender|work_ops|shared",
    "resource_id": "uuid",
    "source_document_id": "uuid",
    "chunk_id": "uuid",
    "acl_principals": ["user:...", "role:...", "group:..."],
    "classification": "internal|confidential|restricted",
    "source_version": "string",
    "index_version": "string",
    "valid_from": "datetime",
    "valid_until": null,
    "retention_policy": "string",
    "provenance_hash": "sha256"
}
```

Payload index phải tạo cho các field lọc chính. `tenant_id` được cấu hình tenant index. Retrieval code không được nhận filter tenant tùy ý từ model; gateway tự inject filter từ trusted `AccessContext`.

## 13.4 Evidence contract

```python
class EvidenceRef(BaseModel):
    evidence_id: UUID
    source_document_id: UUID
    source_version: str
    chunk_id: UUID | None
    page: int | None
    start_offset: int | None
    end_offset: int | None
    quote: str | None
    relevance_score: float
    classification: str
    provenance_hash: str
```

Mọi recommendation quan trọng phải có evidence refs.

# 14. Long-term memory

## 14.1 Các loại memory

- **Working state**: state của run hiện tại; checkpoint store.
- **Episodic memory**: case/meeting trước và outcome.
- **Semantic memory**: policy, SOP, organization và supplier/project knowledge.
- **Procedural memory**: workflow/config đã phê duyệt.
- **Preference memory**: format và channel preference của user.
- **Commitment memory**: quyết định, cam kết, owner, deadline.
- **Audit evidence**: immutable record; không dùng như conversational memory.

## 14.2 Memory write policy

Model không tự ghi mọi nội dung vào long-term memory. Quy trình:

1. Tạo memory candidate.
2. Phân loại loại dữ liệu và sensitivity.
3. Kiểm tra duplication/conflict.
4. Xác định provenance và validity.
5. Policy quyết định auto-write, review hoặc reject.
6. Lưu memory item và index vector nếu cần.

## 14.3 Memory schema

```python
class MemoryItem(BaseModel):
    memory_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    worker_id: str
    memory_type: str
    subject_refs: list[str]
    content: str
    structured_facts: dict[str, object]
    provenance_refs: list[EvidenceRef]
    confidence: float
    classification: str
    valid_from: datetime
    valid_until: datetime | None
    retention_policy: str
    memory_schema_version: str
    created_by_run_id: UUID
```

Memory UI phải cho phép inspect, sửa, vô hiệu hóa và delete theo quyền. Task status, approval state, giá và dữ liệu giao dịch luôn lấy từ system of record, không lấy memory làm nguồn có thẩm quyền.

# 15. Multi-tenant, authorization và entitlement

## 15.1 Phân biệt ba khái niệm

- **Tenant isolation**: dữ liệu khách hàng A không thể truy cập bởi khách hàng B.
- **Authorization**: user nào được làm action nào trên resource nào.
- **Entitlement**: gói trả phí cho phép tính năng, quota, model, retention và isolation nào.

Entitlement không thay thế authorization.

## 15.2 AccessContext

```python
class AccessContext(BaseModel):
    tenant_id: UUID
    workspace_id: UUID
    principal_id: UUID
    roles: set[str]
    groups: set[str]
    scopes: set[str]
    clearance: str
    plan_id: str
    feature_flags: set[str]
```

Context được tạo từ verified token và database membership. Không tin `tenant_id` do client gửi nếu không đối chiếu token/membership.

## 15.3 PostgreSQL RLS

- Tất cả bảng tenant-scoped có `tenant_id NOT NULL`.
- Bật RLS và `FORCE ROW LEVEL SECURITY` khi phù hợp.
- Mỗi transaction set trusted context bằng `SET LOCAL`.
- App runtime role không có `BYPASSRLS`.
- Migration/maintenance role tách riêng.
- CI có test default-deny khi thiếu context.

Ví dụ:

```sql
ALTER TABLE work_ops.action_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_ops.action_items FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_action_items
ON work_ops.action_items
USING (tenant_id = current_setting('app.tenant_id')::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
```

## 15.4 Policy engine

POC:

- Application policy service + RLS.
- Policy interface không phụ thuộc implementation.

Enterprise:

- Cerbos adapter hoặc policy engine tương đương.
- Resource-oriented policy, derived roles và conditions.
- Versioned policy repository và policy tests.

## 15.5 Plan và deployment profile

Tách `plan_id` khỏi `technology_profile`.

| Plan         | Ví dụ entitlement                                                                   |
| ------------ | ----------------------------------------------------------------------------------- |
| Basic        | một DW, quota thấp, shared model, retention ngắn, dữ liệu summary                   |
| Professional | hai DW, model routing tốt hơn, connector và retention cao hơn, detailed evidence    |
| Enterprise   | custom policy, dedicated isolation option, audit/export, private model/network, SLA |

| Technology profile | Mục tiêu                                                                          |
| ------------------ | --------------------------------------------------------------------------------- |
| `low_cost`         | open model/local services, shared deployment, giới hạn context và retention       |
| `balanced`         | managed LLM + self-host data plane, model routing và full evaluation              |
| `premium`          | dedicated endpoints, private network, dedicated shard/deployment, full governance |

## 15.6 Data depth

Quyền xem dữ liệu sâu phải được policy quyết định theo:

- Plan entitlement.
- Role và clearance.
- Resource ownership/department.
- Classification.
- Purpose/action.

Model chỉ nhận evidence đã qua policy filter; không đưa toàn bộ tài liệu vào context rồi yêu cầu model “tự không tiết lộ”.

# 16. API và event contracts

## 16.1 API versioning

- Base path `/api/v1`.
- OpenAPI snapshot commit trong `contracts/openapi/`.
- Breaking change tạo `/api/v2` hoặc compatibility adapter.
- Response lỗi dùng một schema thống nhất.
- Mutation endpoint hỗ trợ `Idempotency-Key`.

## 16.2 Endpoint groups

```text
GET/POST   /api/v1/workers
POST       /api/v1/runs
GET        /api/v1/runs/{runId}
POST       /api/v1/runs/{runId}/resume
GET/POST   /api/v1/approvals
POST       /api/v1/approvals/{id}/decisions
POST       /api/v1/knowledge/documents
GET        /api/v1/knowledge/search
GET/PATCH  /api/v1/memory/{id}
POST       /api/v1/procurement/cases
POST       /api/v1/procurement/cases/{id}/analyze
POST       /api/v1/work-ops/meetings
POST       /api/v1/work-ops/meetings/{id}/generate-actions
POST       /api/v1/work-ops/actions/{id}/dispatch
GET        /api/v1/audit/events
```

## 16.3 Event envelope

```json
{
    "event_id": "uuid",
    "event_type": "work_ops.action.dispatched",
    "schema_version": "1.0",
    "occurred_at": "2026-07-23T00:00:00Z",
    "tenant_id": "uuid",
    "workspace_id": "uuid",
    "aggregate_id": "uuid",
    "correlation_id": "uuid",
    "causation_id": "uuid",
    "actor_id": "uuid",
    "payload": {}
}
```

Consumer phải tolerant với field mới và reject schema version không hỗ trợ.

# 17. Versioning model

![Versioning model](dw_source_blueprint_assets/versioning_model.png)

## 17.1 Platform release

Dùng Semantic Versioning:

- MAJOR: breaking public API/contract.
- MINOR: backward-compatible capability.
- PATCH: backward-compatible fix.

Giai đoạn POC dùng `0.x.y`, nhưng vẫn phải khai báo public contracts.

## 17.2 Các artifact phải version độc lập

- API contract.
- Event schema.
- Worker definition.
- Graph.
- Prompt bundle.
- Tool contract.
- Policy.
- Memory schema.
- Knowledge index.
- Model routing policy.
- Evaluation dataset.
- Database migration.
- UI tool renderer contract.

## 17.3 Release manifest

Mỗi release sinh immutable manifest:

```json
{
    "platform_version": "0.2.0",
    "git_sha": "...",
    "built_at": "...",
    "api_version": "1.0",
    "workers": {
        "tender": {
            "worker_version": "1.0.0",
            "graph_version": "1.0.0",
            "prompt_bundle_version": "1.1.0",
            "toolset_version": "1.0.0",
            "policy_version": "1.0.0"
        },
        "work_ops": {
            "worker_version": "1.0.0",
            "graph_version": "1.0.0",
            "prompt_bundle_version": "1.0.2",
            "toolset_version": "1.0.0",
            "policy_version": "1.0.0"
        }
    },
    "knowledge_index_version": "2026-07-23.1",
    "evaluation_dataset_version": "1.0.0"
}
```

Mọi run lưu release manifest hoặc tham chiếu immutable manifest để tái hiện.

## 17.4 Git và release process

- Trunk-based development, short-lived branch.
- PR bắt buộc.
- Squash merge với Conventional Commit title.
- Protected main branch.
- Automated changelog/release notes.
- Tag release bất biến.
- Migration forward và rollback/runbook.
- Feature flag cho thay đổi rủi ro cao.

# 18. Configuration architecture

## 18.1 Nguyên tắc

- Config không chứa secret.
- Secret chỉ qua environment/secret manager.
- Config được validate lúc startup.
- Environment override rõ ràng.
- Unknown config field làm startup fail ở production.
- Config artifact có version và checksum.

## 18.2 Worker config mẫu

```yaml
schema_version: "1.0"
worker_id: work_ops
worker_version: "1.0.0"
graph_version: "1.0.0"
prompt_bundle_version: "1.0.0"
toolset_version: "1.0.0"
policy_version: "1.0.0"
autonomy_level: A2
model_profile: balanced
memory_policy: work_ops_default_v1
allowed_tools:
    - name: organization.resolve_person
      version: "1.0.0"
    - name: task.prepare
      version: "1.0.0"
    - name: slack.create_task
      version: "1.0.0"
approval_rules:
    cross_department: always
    external_commitment: always
    low_confidence: always
    normal_internal_task: conditional
thresholds:
    assignee_confidence: 0.90
    auto_dispatch_confidence: 0.95
```

## 18.3 Model profile mẫu

```yaml
profile_id: balanced
routing_policy_version: "1.0.0"
structured_extraction:
    provider: managed_primary
    model: extraction_model
    timeout_seconds: 45
reasoning:
    provider: managed_primary
    model: reasoning_model
    timeout_seconds: 90
fallback:
    provider: self_hosted
    model: fallback_model
budgets:
    max_input_tokens_per_run: 120000
    max_cost_usd_per_run: 2.00
```

# 19. Database model tối thiểu

## 19.1 Platform schema

- `platform.tenants`
- `platform.workspaces`
- `platform.users`
- `platform.memberships`
- `platform.roles`
- `platform.plans`
- `platform.entitlements`
- `platform.worker_definitions`
- `platform.worker_runs`
- `platform.run_checkpoints`
- `platform.approval_requests`
- `platform.approval_decisions`
- `platform.tool_executions`
- `platform.audit_events`
- `platform.outbox_events`
- `platform.integrations`
- `platform.external_identities`

## 19.2 Knowledge/memory schema

- `knowledge.documents`
- `knowledge.document_versions`
- `knowledge.chunks`
- `knowledge.entities`
- `knowledge.relations`
- `knowledge.index_jobs`
- `memory.items`
- `memory.revisions`
- `memory.write_candidates`

## 19.3 Tender schema

- `tender.cases`
- `tender.requirements`
- `tender.criteria`
- `tender.suppliers`
- `tender.submissions`
- `tender.evidence_links`
- `tender.compliance_findings`
- `tender.recommendations`

## 19.4 Work Operations schema

- `work_ops.meetings`
- `work_ops.transcript_artifacts`
- `work_ops.decisions`
- `work_ops.action_items`
- `work_ops.assignee_candidates`
- `work_ops.dispatch_requests`
- `work_ops.external_tasks`
- `work_ops.follow_up_events`

## 19.5 Common columns

Tenant-scoped aggregate table có:

```text
id UUID PK
tenant_id UUID NOT NULL
workspace_id UUID NOT NULL
version INTEGER NOT NULL
created_at TIMESTAMPTZ NOT NULL
created_by UUID NOT NULL
updated_at TIMESTAMPTZ NOT NULL
updated_by UUID NOT NULL
```

Dùng optimistic concurrency cho aggregate có nhiều update.

# 20. Security architecture

## 20.1 Authentication

- OIDC Authorization Code + PKCE cho web.
- Service-to-service dùng client credentials hoặc workload identity.
- Local dev dùng Keycloak realm seed.
- API xác minh issuer, audience, signature, expiry và nonce/state theo flow.

## 20.2 Authorization layers

1. Route-level scope check.
2. Application policy check.
3. Tool permission check.
4. PostgreSQL RLS.
5. Qdrant trusted filter injection.
6. Object storage scoped path/presigned URL.

Defense in depth: không phụ thuộc một lớp duy nhất.

## 20.3 Prompt injection và tool safety

- Document content luôn được đánh dấu untrusted.
- Model không được thay system policy bằng instruction trong document.
- Tool allowlist theo worker và run context.
- Không cho model tự truyền tenant ID hoặc credential.
- URL fetch có allowlist, SSRF protection và size limit.
- File parsing tách process/container khi cần.
- Side effect có preview và approval.
- Tool output cũng được xem là untrusted input cho bước tiếp theo.

## 20.4 Secrets

- Không commit secret.
- `.env.example` chỉ có tên biến.
- Credential integration lưu bằng secret reference, không lưu plaintext token trong domain table.
- Redact secret/PII trong logs và traces.
- Rotate credential và revoke integration.

## 20.5 Audit

Audit event tối thiểu:

- Actor, tenant, workspace.
- Worker/run/version.
- Action.
- Resource.
- Policy decision.
- Approval.
- Tool input hash/output hash.
- Evidence refs.
- Timestamp và trace ID.

Audit log append-only; không dùng log application thông thường thay audit trail.

# 21. Observability và AgentOps

## 21.1 OpenTelemetry

Instrument:

- HTTP request.
- Workflow run.
- Node execution.
- Model call.
- Retrieval.
- Rerank.
- Tool call.
- Approval wait/resume.
- Database query ở mức phù hợp.
- Queue/outbox processing.

Không dùng user ID hoặc raw prompt làm metric label có cardinality cao.

## 21.2 Langfuse

Dùng cho:

- LLM traces.
- Prompt version metadata.
- Token/cost/latency.
- Retrieval/tool observations.
- Dataset, experiment và evaluation score.

Langfuse là observability backend chuyên LLM; OpenTelemetry vẫn là instrumentation chuẩn chung.

## 21.3 Metrics tối thiểu

- `dw_run_total{worker,status}`
- `dw_run_duration_seconds{worker}`
- `dw_node_failure_total{worker,node,error_type}`
- `dw_tool_call_total{tool,status}`
- `dw_approval_wait_seconds{worker,approval_type}`
- `dw_model_tokens_total{provider,model,direction}`
- `dw_model_cost_usd_total{worker,provider}`
- `dw_retrieval_hit_rate{worker}`
- `dw_human_intervention_rate{worker}`
- `dw_task_success_rate{worker}`

# 22. Evaluation architecture

## 22.1 Evaluation pyramid

1. Schema/validation tests.
2. Deterministic business-rule tests.
3. Retrieval tests.
4. Tool permission tests.
5. Workflow path tests.
6. Golden dataset task evaluation.
7. LLM-as-judge chỉ cho tiêu chí khó đo deterministic.
8. Human review sample.
9. Business outcome metrics.

## 22.2 Dataset bắt buộc

Mỗi worker có:

- Normal cases.
- Boundary cases.
- Exception cases.
- Failure cases.
- Prompt injection cases.
- Cross-tenant attack cases.
- Missing evidence cases.
- Ambiguous identity cases.

## 22.3 Release gate

Không merge/release khi:

- Task success giảm quá threshold.
- Critical policy test fail.
- Cross-tenant test fail.
- Tool permission test fail.
- Mandatory evidence coverage giảm.
- Cost/latency vượt budget không được chấp thuận.

# 23. Testing strategy

## 23.1 Unit tests

- Domain invariants.
- Value objects.
- Policies/specifications.
- Use cases với fake ports.
- Workflow routing functions.

## 23.2 Integration tests

- PostgreSQL repository + RLS.
- Qdrant filtered retrieval.
- MinIO artifact flow.
- LangGraph checkpoint/resume.
- Outbox processing.
- Connector adapter sandbox/mock server.

## 23.3 Contract tests

- OpenAPI snapshot.
- Event JSON Schema.
- Tool input/output schema.
- Connector canonical contract.
- Generated TypeScript client compile.

## 23.4 Architecture tests

Enforce:

- Domain không import framework/external adapters.
- Tender không import Work Ops internals và ngược lại.
- API không import concrete repository trực tiếp ngoài composition root.
- Provider SDK chỉ xuất hiện trong adapter package.

Dùng `import-linter` hoặc script AST tương đương trong CI.

## 23.5 End-to-end tests

- Upload transcript → generate actions → approve → mock dispatch → audit.
- Upload tender documents → analyze → approve recommendation → export.
- User tenant A không đọc run/document tenant B.
- Resume run sau worker restart.

# 24. CI/CD pipeline

## 24.1 Local quality gate

`pre-commit` chạy nhanh:

- Ruff lint.
- Ruff format check.
- Basic secret scan.
- YAML/JSON validation.
- Commit message được kiểm tra ở CI hoặc commit-msg hook.

Không chạy full integration/eval ở pre-commit.

## 24.2 Pull request CI

```text
1. Validate repository/config/contracts
2. Python lint + format
3. Python type check
4. Frontend lint + type check
5. Unit tests
6. Architecture tests
7. Integration tests with Postgres/Qdrant/Redis/MinIO
8. OpenAPI/event/tool contract tests
9. Security and dependency scan
10. Eval smoke suite
11. Build containers
12. Docker Compose smoke test
```

## 24.3 Main/release pipeline

- Full eval regression.
- Migration test từ version trước.
- Generate SBOM.
- Build/sign image.
- Generate release manifest/changelog.
- Deploy dev/staging.
- Smoke/canary.
- Manual production approval.
- Rollback instructions.

GitHub Actions reusable workflows được dùng để tránh copy job giữa app/package.

# 25. Coding standards

## 25.1 Python

- Full type hints cho public API.
- `from __future__ import annotations` nếu cần.
- Pydantic cho boundary DTO; dataclass/value object cho domain.
- Không dùng mutable default.
- Không dùng catch-all `except Exception` nếu không re-raise với context/taxonomy.
- Không dùng global mutable singleton.
- Dependency injection qua constructor/factory.
- Async chỉ tại IO boundary; domain rule synchronous.
- Structured logging, không ghép chuỗi chứa sensitive data.
- Function nhỏ, một trách nhiệm.
- Public class/function có docstring khi intent không hiển nhiên.

## 25.2 TypeScript/React

- Strict TypeScript.
- Không dùng `any` trừ adapter boundary có comment và validation.
- Zod validate dữ liệu runtime.
- Generated API types là source of truth.
- Business permission không chỉ ẩn button; backend vẫn enforce.
- Feature module không import private file của feature khác.
- Accessible keyboard/focus cho approval và tool UI.

## 25.3 Không over-engineer

Pattern chỉ được thêm khi có variation, side effect, lifecycle hoặc boundary thật. Không tạo interface một method cho mọi class nếu không có khả năng thay implementation/test seam.

# 26. Dependency injection và composition root

Không dùng service locator trong domain/application.

`apps/api/src/dw_api/bootstrap.py` tạo:

- Settings.
- Database engine/session factory.
- Repositories/UoW factories.
- Qdrant/object store/cache clients.
- Model gateway adapters.
- Connector adapters.
- Policy/authorization adapters.
- Workflow registry.
- Use case handlers.

Test có bootstrap riêng với fake/mock adapters.

# 27. POC deployment profiles

## 27.1 Local development

Docker Compose:

- PostgreSQL.
- Qdrant.
- Redis/Valkey.
- MinIO.
- Keycloak.
- Langfuse optional profile.
- API.
- Worker.
- Web.

## 27.2 Low-cost profile

- Shared deployment.
- Self-host model endpoint hoặc low-cost managed model.
- Local/self-host Qdrant/Postgres.
- Basic observability.
- Short retention.

## 27.3 Balanced profile

- Managed reasoning model + fallback.
- Managed Postgres hoặc HA self-host.
- Qdrant Cloud/self-host cluster.
- Langfuse + OTel collector.
- Central policy service.

## 27.4 Premium profile

- Dedicated tenant deployment hoặc shard.
- Private network/model endpoint.
- KMS/HSM-managed secrets.
- SIEM integration.
- Full audit/data retention.
- Dedicated performance budget và SLA.

# 28. Claude Code execution contract

Claude Code phải coi tài liệu này là specification, không phải gợi ý. Trước khi code phải tạo plan và liệt kê các ADR cần chốt. Sau đó triển khai theo phase, mỗi phase phải chạy test và cập nhật progress.

## 28.1 Phase 0 - Repository bootstrap

Tạo:

- Monorepo structure.
- uv workspace.
- pnpm workspace.
- Quality configs.
- Docker Compose.
- Make/Task commands.
- README và CLAUDE.md.

Acceptance:

```bash
make bootstrap
make lint
make test-unit
```

đều chạy được.

## 28.2 Phase 1 - Shared kernel và platform foundation

Tạo:

- IDs/value objects.
- Tenant/access context.
- Plan/entitlement model.
- Authorization port.
- Approval model.
- Audit/outbox model.
- PostgreSQL connection và migrations.
- RLS helper và tests.

Acceptance:

- Seed được tenant A/B.
- Test tenant A không query được row tenant B.

## 28.3 Phase 2 - Agent runtime foundation

Tạo:

- Worker definition registry.
- LangGraph workflow runner adapter.
- Checkpoint persistence.
- Interrupt/approval flow.
- Tool registry/executor.
- Model gateway with mock model adapter.
- Trace middleware.

Acceptance:

- Demo graph pause tại approval.
- Restart worker và resume thành công.

## 28.4 Phase 3 - Work Operations vertical slice

Tạo:

- Meeting/action domain.
- Transcript upload.
- Mock structured extraction.
- Work Ops graph v1.
- Approval UI.
- Mock Slack/Teams task dispatch.
- Audit timeline.

Acceptance:

- E2E meeting-to-action test pass.

## 28.5 Phase 4 - Tender vertical slice

Tạo:

- Tender domain.
- Document upload.
- Requirement extraction schema.
- Compliance matrix.
- Deterministic weighted scoring.
- Recommendation approval.

Acceptance:

- E2E tender test pass với fixture.

## 28.6 Phase 5 - Knowledge và memory

Tạo:

- Document ingestion.
- Qdrant payload/index setup.
- Trusted filtered retrieval.
- Evidence refs.
- Memory candidate/write flow.

Acceptance:

- Retrieval luôn có tenant filter.
- Cross-tenant vector test fail-closed.
- Recommendation có evidence.

## 28.7 Phase 6 - UI và observability

Tạo:

- Next.js shell.
- CopilotKit/AG-UI integration.
- Domain pages.
- Approval inbox.
- Run timeline.
- OTel + Langfuse integration.

Acceptance:

- User xem run state và approve được.
- Trace thể hiện node/model/retrieval/tool.

## 28.8 Phase 7 - Hardening

Tạo:

- Eval datasets.
- Architecture tests.
- Security tests.
- CI workflows.
- Release manifest.
- ADR/runbook/threat model.

# 29. Definition of Done cho source base

Source base chỉ được coi là hoàn thành khi:

- Không có placeholder package trống chỉ chứa TODO.
- `docker compose up` khởi động dependency cốt lõi.
- API health/readiness pass.
- Web build pass.
- Migrations chạy từ blank database.
- Seed demo chạy idempotent.
- Hai vertical slice có fixture và test.
- Approval pause/resume hoạt động.
- RLS isolation test pass.
- Qdrant tenant filter test pass.
- Tool permission test pass.
- Audit event được ghi cho run và side effect.
- OpenAPI được generate và frontend client compile.
- CI chạy xanh.
- README có exact commands.
- ADR nêu rõ các quyết định còn deferred.

# 30. Những điều Claude Code không được làm

- Không đặt toàn bộ code trong `main.py` hoặc `services.py` khổng lồ.
- Không cho domain import FastAPI/SQLAlchemy/LangGraph.
- Không gọi provider SDK trực tiếp từ API route hoặc workflow node.
- Không dùng một generic `BaseRepository` che mất semantics aggregate.
- Không lưu tenant filter do model/client truyền trực tiếp.
- Không lấy Redis làm source of truth.
- Không tạo collection Qdrant riêng cho từng tenant nhỏ theo mặc định.
- Không lưu raw token integration trong database/log.
- Không tự dispatch side effect critical khi chưa approval.
- Không để prompt/config không có version.
- Không dùng mock âm thầm ở production profile.
- Không swallow exception và trả success.
- Không sinh code không có test cho security boundary.
- Không thêm multi-agent chỉ để “trông SOTA”.

# 31. Lệnh developer chuẩn

Source base phải cung cấp các lệnh tương đương:

```bash
make bootstrap          # install dependencies and initialize local config
make infra-up           # start Postgres/Qdrant/Redis/MinIO/Keycloak
make migrate            # run database migrations
make seed               # seed demo tenants/users/data
make dev                # run API, worker and web
make lint               # Python + TypeScript lint/format check
make typecheck          # Python + TypeScript type check
make test-unit
make test-integration
make test-architecture
make test-eval-smoke
make test-e2e
make test-all
make generate-contracts
make release-manifest
```

# 32. ADR bắt buộc

Claude Code tạo tối thiểu:

- ADR-001: Một monorepo, modular monolith.
- ADR-002: Hai bounded context, không dùng super-agent.
- ADR-003: Clean/Hexagonal dependency rule.
- ADR-004: LangGraph cho agent workflow; Temporal deferred qua port.
- ADR-005: PostgreSQL system of record + RLS.
- ADR-006: Qdrant multitenancy bằng payload/tenant index.
- ADR-007: CopilotKit UI adapter và khả năng thay thế.
- ADR-008: Versioning code, graph, prompt, tool, policy và eval.
- ADR-009: Outbox cho external side effect.
- ADR-010: Human approval và autonomy A2 trong POC.

# 33. Rủi ro cần theo dõi

| Rủi ro                                 | Biện pháp                                                                      |
| -------------------------------------- | ------------------------------------------------------------------------------ |
| Shared platform trở thành “god module” | public contract nhỏ, package dependency test, ownership rõ                     |
| Agent output không ổn định             | structured output, deterministic gate, eval regression                         |
| Rò tenant qua retrieval/cache          | trusted context, RLS, Qdrant filter injection, tenant-aware keys, attack tests |
| Side effect trùng khi retry            | outbox, idempotency key, external reference uniqueness                         |
| Memory contamination                   | write candidate, provenance, confidence, review, validity/TTL                  |
| Prompt injection                       | untrusted content boundary, tool allowlist, policy gate, HITL                  |
| Cost tăng                              | model routing, token budget, trace cost, plan quotas                           |
| Workflow bị kẹt                        | durable checkpoint, timeout, retry, escalation, admin recovery                 |
| Tách microservice khó                  | ports/adapters, integration events, no cross-context internals                 |
| Version không tái hiện được            | release manifest, immutable artifacts, trace metadata                          |

# 34. Khuyến nghị triển khai ngay

Bản source đầu tiên nên ưu tiên **thin vertical slice**, không xây tất cả platform trước rồi mới có demo:

1. Bootstrap monorepo và boundary.
2. Meeting-to-action với mock model + mock connector.
3. Thêm approval/checkpoint/audit.
4. Thêm tenant/RLS.
5. Thay mock model bằng provider adapter.
6. Thêm Qdrant/evidence.
7. Dùng cùng platform để dựng Tender workflow.
8. Sau khi hai slice chạy ổn mới thêm Temporal, Cerbos, connector thứ hai hoặc graph database.

# 35. Tài liệu tham khảo kỹ thuật chính thức

1. CopilotKit LangGraph/Python, generative UI và HITL: https://docs.copilotkit.ai/langgraph-python
2. CopilotKit repository và MIT license: https://github.com/CopilotKit/CopilotKit
3. assistant-ui documentation: https://www.assistant-ui.com/docs
4. Open WebUI license: https://github.com/open-webui/open-webui/blob/main/LICENSE
5. LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
6. LangGraph interrupts/HITL: https://docs.langchain.com/oss/python/langgraph/interrupts
7. Qdrant multitenancy: https://qdrant.tech/documentation/manage-data/multitenancy/
8. Qdrant indexing/tenant index: https://qdrant.tech/documentation/manage-data/indexing/
9. PostgreSQL Row-Level Security: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
10. FastAPI bigger applications: https://fastapi.tiangolo.com/tutorial/bigger-applications/
11. SQLAlchemy asyncio: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
12. Alembic documentation: https://alembic.sqlalchemy.org/en/latest/
13. uv workspaces: https://docs.astral.sh/uv/concepts/projects/workspaces/
14. Ruff: https://docs.astral.sh/ruff/
15. Keycloak securing apps/OIDC: https://www.keycloak.org/securing-apps/overview
16. Cerbos policies: https://docs.cerbos.dev/cerbos/latest/policies/index.html
17. OpenTelemetry signals: https://opentelemetry.io/docs/concepts/signals/
18. Langfuse self-hosting: https://langfuse.com/self-hosting
19. Temporal Python SDK: https://docs.temporal.io/develop/python
20. Slack Events API: https://docs.slack.dev/apis/events-api/
21. Semantic Versioning: https://semver.org/
22. Conventional Commits: https://www.conventionalcommits.org/en/v1.0.0/
23. GitHub Actions reusable workflows: https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows
24. pre-commit: https://pre-commit.com/

---

**Kết luận:** Source base phải được xây như một nền tảng Digital Worker có boundary rõ ràng, không phải một chatbot gắn nhiều tool. Một monorepo và UI chung giúp tái sử dụng platform; hai bounded context, hai workflow và hai quyền hạn riêng giúp bảo mật, maintain và tách rời về sau. Clean/Hexagonal Architecture, typed contracts, RLS, trusted retrieval filter, versioned agent artifacts, human approval và evaluation gate là các yêu cầu bắt buộc ngay từ POC.
