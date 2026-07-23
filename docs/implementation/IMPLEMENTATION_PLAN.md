# Digital Worker Platform — Implementation Plan

- **Status**: IN PROGRESS — Phase 0 DONE, chuẩn bị Phase 1
- **Ngày tạo**: 2026-07-23
- **Specification nguồn**: `CLAUDE.md`, `docs/architecture/Digital_Worker_Source_Base_Blueprint_v2.md` (binding)
- **Phase mapping**: cấu trúc 7 phase dưới đây ánh xạ lại §28 của blueprint (xem ADR-011); toàn bộ deliverable §28.1–§28.8 đều được bao phủ.

## Quy ước chung cho mọi phase

Quality gate bắt buộc sau mỗi phase (không chuyển phase khi chưa pass):

```bash
make format && make lint && make typecheck
make test-unit && make test-architecture
# + test đặc thù của phase (integration/contract/e2e/eval)
```

Sau mỗi phase: cập nhật bảng Progress cuối file này, tóm tắt file thay đổi, ghi lại command + kết quả, commit Conventional Commits.

Nguyên tắc xuyên suốt:

- Không placeholder-only package; mọi deferred dependency có typed port + working mock adapter.
- Domain không import FastAPI/SQLAlchemy/LangGraph/Qdrant/provider SDK (enforce bằng import-linter từ Phase 0).
- Mọi side effect: policy → validation → idempotency → audit → (approval nếu critical).
- Mọi artifact (worker/graph/prompt/tool/policy/event/index/dataset) có version ngay từ khi tạo.

## Ràng buộc môi trường (ghi nhận tại inspection 2026-07-23)

| Tool      | Trạng thái host             | Kế hoạch                                                                                                                                                                                                                           |
| --------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python    | 3.11.9 (cần 3.12)           | `uv python install 3.12` quản lý riêng                                                                                                                                                                                             |
| uv        | chưa có                     | cài qua winget/pip trong bootstrap                                                                                                                                                                                                 |
| make      | chưa có                     | cài qua winget (ezwinports.make) trong bootstrap; mọi target chạy được trong Git Bash                                                                                                                                              |
| node/pnpm | chưa có                     | cài Node LTS qua winget + corepack enable pnpm                                                                                                                                                                                     |
| Docker    | **chưa cài Docker Desktop** | **BLOCKER cho acceptance container-based** — cần người dùng cài (admin + WSL2). File Docker/Compose vẫn được tạo đầy đủ; validate `docker compose config` và integration/E2E test container-based sẽ chạy ngay khi Docker sẵn sàng |

---

## Phase 0 — Repository bootstrap và Docker foundation

### Scope

- Cài đặt toolchain còn thiếu (uv, Python 3.12, make, Node LTS, pnpm).
- Monorepo skeleton đúng cấu trúc bắt buộc của CLAUDE.md — mỗi package có code thật tối thiểu (không placeholder): `dw_kernel` với IDs/value objects/errors/result/clock port + unit tests là nội dung thật đầu tiên; các package khác khởi tạo với `py.typed`, pyproject, module version (`__version__`) và ít nhất một contract/test thật sẽ được mở rộng ở phase sau.
- uv workspace (root `pyproject.toml` + per-package pyproject, một `uv.lock`).
- pnpm workspace (`pnpm-workspace.yaml`, `package.json`, `turbo.json`, lockfile).
- Quality configs: Ruff (lint+format), mypy strict, import-linter contracts (layer rule + context independence + provider SDK confinement), pytest config, pre-commit, `.editorconfig`, `.gitignore`, `.dockerignore`.
- Docker foundation:
    - `infra/docker/api.Dockerfile`, `worker.Dockerfile`, `web.Dockerfile` — multi-stage, non-root user, pinned base images.
    - `infra/compose/docker-compose.yml` + profiles: mặc định (`infra`) chỉ chạy PostgreSQL, Qdrant, Valkey, MinIO, Keycloak; profile `full` thêm migration job + API + Worker + Web; profile `observability` thêm Langfuse (+ dependencies của nó).
    - Healthcheck cho mọi service; `depends_on: condition: service_healthy`; named volumes; internal network riêng; migration job an toàn (chạy Alembic rồi exit 0, API/Worker đợi job hoàn thành).
    - `.env.example` đầy đủ tên biến, không secret thật.
- `Makefile` với đủ target: `bootstrap, infra-up, infra-down, dev, docker-up, docker-down, db-migrate, db-seed, lint, format, typecheck, test-unit, test-integration, test-architecture, test-contract, eval-smoke, ci` + alias tương thích CLAUDE.md (`migrate, seed, test-eval-smoke, test-e2e, test-all, generate-contracts, release-manifest, infra-up…`).
- `README.md` (exact commands, demo credentials sẽ bổ sung ở Phase 1), `CHANGELOG.md`, `LICENSE`.
- ADR-001 → ADR-004, ADR-011 → ADR-014 trong `docs/adr/`.
- `.github/workflows/ci.yml` khởi đầu (lint/typecheck/unit/architecture).

### Files/packages dự kiến

`Makefile`, `pyproject.toml`, `uv.lock`, `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `turbo.json`, `.env.example`, `.gitignore`, `.dockerignore`, `.editorconfig`, `.pre-commit-config.yaml`, `README.md`, `CHANGELOG.md`, `LICENSE`, `apps/api/**`, `apps/worker/**`, `apps/web/**` (Next.js init strict TS + Tailwind + shadcn/ui), `packages/python/*/pyproject.toml` + `src/**`, `packages/typescript/{ui,api-client,contracts,agent-ui}/**`, `infra/docker/*.Dockerfile`, `infra/compose/docker-compose.yml`, `configs/**` (skeleton có schema_version), `contracts/**`, `db/**`, `evals/**`, `scripts/{bootstrap.*, verify_architecture.py}`, `docs/adr/ADR-001..004,011..014`, `.github/workflows/ci.yml`.

### Acceptance criteria

- `make bootstrap` cài dependency Python + Node thành công từ máy sạch (đã có uv/node hoặc tự cài).
- `make lint`, `make format`, `make typecheck` pass.
- `make test-unit` pass (unit tests thật của `dw_kernel`).
- `make test-architecture` pass (import-linter chạy và enforce cả 4 rule §23.4).
- `docker compose config` hợp lệ cho cả 3 profile (chạy được khi Docker sẵn sàng).
- Không package nào rỗng chỉ chứa TODO.

### Tests phải chạy

`test-unit` (dw_kernel value objects/errors/result), `test-architecture` (import-linter), lint/typecheck toàn workspace, `pnpm -r typecheck` cho TS.

### Dependencies

Không có (phase đầu). Cần quyền cài tool qua winget.

### Risks

- Winget cần tương tác/quyền → fallback: pip install uv, standalone node zip, make từ Git for Windows SDK; ghi rõ hướng dẫn thủ công trong README.
- Docker chưa có trên host → `docker compose config` chưa verify được bằng CLI thật; mitigate: YAML validate + verify ngay khi Docker được cài (ghi nhận trạng thái trong Progress).
- Resolve version stable (LangGraph/CopilotKit/Next.js) có thể lệch tương thích → pin theo lockfile, smoke import test ngay tại Phase 0.

### Definition of Done

Toàn bộ acceptance pass, quality gate pass, ADR-001..004/011..014 committed, Progress cập nhật, commit `feat: bootstrap monorepo and docker foundation (phase 0)`.

---

## Phase 1 — Shared kernel, tenancy, identity, entitlement và authorization

### Scope

- `dw_kernel` hoàn thiện: `TenantId`, `WorkspaceId`, `UserId`, `EntityId`, `Money`, `UtcClock`/`IdGenerator` ports, base `DomainEvent`, error taxonomy, `Result`, page/cursor primitives.
- `dw_platform`:
    - Domain: Tenant, Workspace, User, Membership, Role, Plan, Entitlement.
    - `AccessContext` (đúng schema §15.2) — build từ verified token + DB membership, không tin client `tenant_id`.
    - `AuthorizationPort` (RBAC + ABAC attributes), `EntitlementPort` (tách riêng authorization), policy service nội bộ (Specification objects), decision + reason.
    - Approval model: `ApprovalRequest`/`ApprovalDecision` + service.
    - Audit: append-only `audit_events` + `AuditPort`; Outbox: `outbox_events` + UoW tích hợp.
- Persistence: SQLAlchemy 2 async mappings (imperative, tách khỏi domain), Repository + UnitOfWork, Alembic migration đầu tiên (schemas `platform`), RLS: enable + FORCE + policies + `SET LOCAL app.tenant_id/app.workspace_id` per transaction; role runtime (`dw_app`) không BYPASSRLS, role migration (`dw_migrator`) riêng.
- Identity: `TokenVerifierPort` + `DevIdentityAdapter` (JWT local) + `KeycloakOidcAdapter` (verify issuer/audience/signature/expiry); Keycloak realm seed JSON trong compose.
- API: middleware auth → AccessContext, error schema thống nhất, `/api/v1/health` + `/api/v1/ready`, route `GET /api/v1/me`.
- Seed idempotent (`db/seeds` + `scripts/seed_demo.py`): 2 tenant (A/B), workspaces, users, roles, plans, entitlements — chạy lại không tạo trùng (upsert theo natural key).
- `make db-migrate`, `make db-seed` hoạt động; migration job trong compose dùng cùng đường dẫn này.

### Files/packages dự kiến

`packages/python/dw_kernel/**`, `packages/python/dw_platform/**`, `apps/api/src/dw_api/{bootstrap.py,lifespan.py,middleware/**,dependencies/**,exception_handlers.py,routes/v1/**}`, `db/migrations/**`, `db/rls/**`, `db/seeds/**`, `scripts/seed_demo.py`, `configs/plans/**`, `docs/adr/ADR-005`, `docs/adr/ADR-013` (cập nhật nếu cần), README (demo credentials).

### Acceptance criteria

- Migration chạy từ blank database pass; downgrade một bậc pass.
- Seed tenant A/B idempotent (chạy 2 lần, số row không đổi).
- RLS test: session set tenant A không đọc/ghi được row tenant B; thiếu context → default-deny (0 rows / lỗi).
- Authorization unit tests: allow/deny theo role/scope; entitlement check độc lập với authorization check.
- `/api/v1/me` trả AccessContext từ dev token; token sai → 401; thiếu membership → 403.

### Tests phải chạy

Unit (value objects, policies, approval, entitlement), Integration (PostgreSQL repository + RLS + default-deny — cần Docker; nếu Docker chưa sẵn sàng: đánh dấu BLOCKED trong Progress, không báo pass), Architecture, API contract snapshot đầu tiên.

### Dependencies

Phase 0; Docker (cho integration test).

### Risks

- RLS + asyncpg connection pooling: `SET LOCAL` phải nằm trong transaction, kiểm soát bằng UoW; test leak connection.
- Windows + Testcontainers có thể không khả dụng khi thiếu Docker → integration test tách marker `integration`, skip-with-loud-warning khi infra thiếu (không đếm là pass).

### Definition of Done

Acceptance + quality gate pass (integration pass hoặc BLOCKED có ghi chú rõ), ADR-005 committed, Progress cập nhật, commit phase 1.

---

## Phase 2 — Agent runtime, model gateway, memory, knowledge và tool registry

### Scope

- `dw_agent_runtime`:
    - Contracts: `WorkerDefinition`, `RunContext`, `ToolDefinition` (đúng §10) — immutable, versioned.
    - `WorkflowRunnerPort` + `LangGraphWorkflowRunner` adapter; checkpoint persistence vào PostgreSQL (`platform.run_checkpoints`); interrupt ↔ `ApprovalRequest` mapping; resume sau restart.
    - Worker registry (load từ `configs/workers/*.yaml`, validate fail-fast, checksum).
    - Tool registry + tool executor 8 bước (§10.3): resolve theo (name, version) → validate input → authz/policy → mask telemetry → execute (timeout/retry) → validate output → audit → typed result. Idempotency key bắt buộc cho side effect.
    - Model gateway: `ModelGateway` port (`generate_structured`), `MockModelAdapter` (deterministic, fixture-driven, schema-valid — default cho local/test), `OpenAICompatibleAdapter` (real, bật qua env, fail-fast ở production profile nếu thiếu key), model profile config (`configs/models/*.yaml`), Strategy routing, token/cost accounting.
    - Node middleware: trace span, timeout, retry, tenant validation, cost, redaction, node version, error taxonomy.
- `dw_knowledge`: document ingestion (MinIO artifact + `knowledge.documents/chunks` PG), chunking, `VectorSearchPort` + `QdrantVectorSearchAdapter`, **retrieval gateway là nơi duy nhất inject filter tenant/workspace/ACL từ `AccessContext`** (payload schema §13.3, payload index + tenant index), `EvidenceRef` contract, evidence pack + provenance hash.
- `dw_memory`: `MemoryItem` (§14.3), write-candidate flow 6 bước (§14.2), policy auto-write/review/reject, PG + Qdrant adapters, retention/validity.
- `dw_connectors`: canonical contracts (`TaskConnectorPort`, `OrganizationPersonRef` ACL), `MockTaskConnectorAdapter` hoạt động thật (persist, idempotent, trả `ExternalTaskRef`), credential reference model (không plaintext token).
- Migrations: `platform.worker_definitions/worker_runs/run_checkpoints/tool_executions`, `knowledge.*`, `memory.*`.
- Demo graph nhỏ (2–3 node + approval interrupt) trong dw_agent_runtime tests để chứng minh pause/resume — không phải worker nghiệp vụ.

### Files/packages dự kiến

`packages/python/dw_agent_runtime/**`, `dw_knowledge/**`, `dw_memory/**`, `dw_connectors/**`, `db/migrations/**`, `configs/{workers,models,tools,prompts}/**`, `contracts/tools/**`, `docs/adr/ADR-006` (Qdrant multitenancy), ADR-012 cập nhật.

### Acceptance criteria

- Demo graph chạy: pause tại approval interrupt, kill process, restart, resume thành công từ checkpoint (integration test).
- Tool executor: gọi tool thiếu scope → deny + audit event; input/output sai schema → typed error; side effect có idempotency key, gọi lại không thực thi lần hai.
- Retrieval: mọi query qua gateway đều chứa tenant/workspace filter (unit test assert trên filter object); cross-tenant vector search trả rỗng (integration, cần Qdrant); code path không tồn tại để caller truyền filter tenant tùy ý.
- MockModelAdapter trả structured output validate qua Pydantic; registry fail-fast khi config trỏ tool/model không tồn tại.
- Memory write candidate → policy quyết định → item được lưu với provenance.

### Tests phải chạy

Unit (registry, executor, policies, gateway routing, chunking), Integration (checkpoint/resume, Qdrant filtered retrieval, MinIO artifact, outbox), Architecture (LangGraph/Qdrant/provider SDK chỉ trong adapter modules), Contract (tool schemas).

### Dependencies

Phase 1 (AccessContext, audit, outbox, migrations infra).

### Risks

- LangGraph checkpoint API thay đổi theo version → pin version, adapter bọc kín, test resume là guard.
- Interrupt ↔ approval mapping phức tạp → demo graph tối thiểu chứng minh trước khi dùng cho slice thật.

### Definition of Done

Acceptance + quality gate pass, ADR-006 committed, Progress cập nhật, commit phase 2.

---

## Phase 3 — Meeting-to-action vertical slice (work_ops)

### Scope

- `dw_work_ops` đầy đủ 5 lớp (§9): domain (MeetingSession, TranscriptArtifact, DecisionRecord, ActionItem, AssigneeResolution, DispatchRequest, ExternalTaskLink + events + policies `CanAutoDispatchAction`), application (commands/queries/handlers/ports/DTO), workflows/v1 (graph 14 node §11.1, `WorkOpsState` §11.2 typed + schema_version, routing, nodes gọi port — không SQL/SDK), adapters (persistence, transcript parser, organization resolver từ seeded org data, dispatch qua `dw_connectors`), presentation (routes `/api/v1/work-ops/**`).
- Approval flow: POLICY_GATE tạo `ApprovalRequest` (§11.3 rules) → HUMAN_REVIEW interrupt → approve qua API/UI → resume → DISPATCH_TASKS qua MockTaskConnector (outbox + idempotency `tenant:action:connector:version`) → external ref + audit timeline.
- Worker run lưu `release_manifest_ref` + toàn bộ artifact versions.
- Fixtures: transcript mẫu (vi/en) trong `db/fixtures`; org data seed (phòng ban, người, external identity mapping).
- Web: routes `/work-ops/meetings`, `/work-ops/meetings/[id]`, `/work-ops/actions`, `/approvals` (approval inbox nhận `ApprovalRequest` schema), run timeline component; API client generate từ OpenAPI; agent state qua `agent-ui` adapter (CopilotKit).
- API endpoints §16.2 nhóm work-ops + runs + approvals.

### Files/packages dự kiến

`packages/python/dw_work_ops/**`, `apps/api/routes/v1/{work_ops,runs,approvals}.py`, `apps/worker/src/dw_worker/**` (outbox processor + dispatch consumer), `apps/web/features/{work-ops,approvals}/**`, `packages/typescript/{api-client,contracts,agent-ui}/**`, `db/migrations` (`work_ops.*` + RLS), `db/fixtures/transcripts/**`, `configs/workers/work_ops.yaml`, `configs/prompts/work_ops/**` (versioned bundle), `contracts/openapi/openapi.json`, e2e test.

### Acceptance criteria

- E2E (integration): upload transcript → generate-actions → run pause tại approval → approve → resume → MockTaskConnector dispatch → external task ref persisted → audit timeline đầy đủ (run, policy decision, approval, tool call, dispatch).
- Reject path: từ chối approval → run kết thúc không dispatch, audit ghi lý do.
- Retry dispatch không tạo task trùng (idempotency test).
- Cross-tenant: user tenant B không thấy meeting/run/approval tenant A (API 403/404 + RLS).
- Web build pass; approval inbox approve được thật qua API.
- OpenAPI snapshot cập nhật; generated TS client compile.

### Tests phải chạy

Unit (domain invariants, routing, policies), Integration (E2E slice, outbox, idempotency), Architecture (tender/work_ops independence), Contract (OpenAPI snapshot + client compile), Web typecheck/build.

### Dependencies

Phase 1, 2.

### Risks

- CopilotKit ↔ LangGraph version tương thích → cô lập trong `agent-ui`; nếu bất ổn, UI vẫn hoạt động qua REST polling (adapter thay thế được — đúng ADR-007).
- Assignee resolution mock cần deterministic để test ổn định → resolver dựa trên seeded org data, không LLM.

### Definition of Done

Acceptance + quality gate pass, Progress cập nhật, commit phase 3. Đây là mốc "first working vertical slice".

---

## Phase 4 — Tender-analysis vertical slice (tender)

### Scope

- `dw_tender` đầy đủ 5 lớp: domain (TenderCase, Requirement, EvaluationCriterion, SupplierSubmission, ComplianceFinding, TenderRecommendation, ApprovalDecision), application, workflows/v1 (graph 13 node §12.1, `TenderState` §12.3), adapters, presentation (`/api/v1/procurement/**`).
- Document upload (MinIO) + parse fixture documents (RFQ + supplier submissions mẫu).
- Requirement extraction qua MockModelAdapter → typed schema; retrieval policies/history qua knowledge gateway → evidence pack.
- **Deterministic scoring**: weights/mandatory criteria/threshold trong `configs/policies/tender_scoring_v1.yaml` (versioned); LLM chỉ đề xuất evidence/score thô; DETERMINISTIC_COMPLIANCE_GATE bằng code; không đạt mandatory nếu thiếu evidence.
- Recommendation + `EvidenceRef` bắt buộc → ApprovalRequest → HUMAN_REVIEW → EXPORT_EVALUATION_PACK (JSON/CSV vào MinIO) → CLOSE_AND_WRITE_MEMORY (episodic memory candidate).
- Web: `/procurement/cases`, `/procurement/cases/[caseId]` (compliance matrix + evidence viewer), `/suppliers`, `/evaluations`.
- Migrations `tender.*` + RLS.

### Files/packages dự kiến

`packages/python/dw_tender/**`, `apps/api/routes/v1/procurement.py`, `apps/web/features/procurement/**`, `db/migrations` (`tender.*`), `db/fixtures/tender/**`, `configs/workers/tender.yaml`, `configs/policies/tender_scoring_v1.yaml`, `configs/prompts/tender/**`, cập nhật OpenAPI + client.

### Acceptance criteria

- E2E: create case → upload fixture documents → analyze → requirements extracted (typed) → compliance matrix built → deterministic scoring đúng expected values (golden numbers trong test) → recommendation có evidence refs → approval pause/resume → evaluation pack exported vào MinIO.
- Mandatory criterion thiếu evidence → không được kết luận "đạt" (negative test).
- Scoring hoàn toàn deterministic: cùng input → cùng score (chạy 2 lần).
- Cross-tenant isolation cho tender case (SQL + Qdrant).
- Tender không import work_ops internals và ngược lại (architecture test đã enforce, thêm test cụ thể).

### Tests phải chạy

Unit (scoring engine, compliance gate, domain), Integration (E2E slice, MinIO export, Qdrant evidence), Architecture, Contract.

### Dependencies

Phase 1, 2 (platform + runtime); độc lập với Phase 3 về domain nhưng sau về thứ tự để tái dùng pattern.

### Risks

- Scoring config sai lệch spec → golden test với expected values duyệt tay trong `evals/expected`.
- Document parsing phức tạp → POC dùng fixture text/JSON có cấu trúc, parser port cho PDF thật để sau.

### Definition of Done

Acceptance + quality gate pass, Progress cập nhật, commit phase 4.

---

## Phase 5 — Evaluation, observability, audit và release/versioning

### Scope

- `dw_observability`: OTel instrumentation (HTTP, run, node, model call, retrieval, tool, approval wait, outbox), structured logging + redaction, metric names §21.3, Langfuse adapter sau port (bật/tắt qua env, compose profile `observability`).
- Trace metadata: tenant/workspace safe IDs, worker + toàn bộ artifact versions, run/node/model/retrieval/tool/approval, latency/token/cost, error taxonomy.
- `dw_evals`: dataset schema (versioned), deterministic graders, LLM-judge port (mock judge cho POC), regression runner, report generator.
- `evals/datasets`: cho mỗi worker — normal/boundary/exception/failure + **prompt injection + cross-tenant attack + missing evidence + ambiguous identity** cases; `evals/expected` golden outputs.
- `make eval-smoke` chạy subset nhanh; security evals (injection không đổi policy, cross-tenant fail-closed, thiếu evidence không kết luận).
- Release/versioning: `scripts/release_manifest.py` sinh manifest immutable (§17.3) → `make release-manifest`; mọi worker run persist manifest reference (đã cài từ Phase 3, verify lại); CHANGELOG tự động từ Conventional Commits.
- CI hoàn thiện: đủ 12 bước §24.2 (validate → lint → typecheck → unit → arch → integration services → contract → security scan (pip-audit/pnpm audit + secret scan) → eval smoke → build containers → compose smoke), reusable workflows, `eval-regression.yml`, `security.yml`, `release.yml`.
- Audit viewer: `/audit` page + `GET /api/v1/audit/events`.

### Files/packages dự kiến

`packages/python/dw_observability/**`, `dw_evals/**`, `evals/**`, `scripts/{run_evals.py,release_manifest.py}`, `.github/workflows/**`, `apps/web/features/audit/**`, `infra/compose` (profile observability + Langfuse), `docs/adr/ADR-008,009,010` (hoàn thiện nếu chưa), `contracts/events/**` (JSON Schema + versioned envelope).

### Acceptance criteria

- `make eval-smoke` pass cho cả 2 worker; security eval cases pass (fail-closed).
- Trace một run hiển thị đủ node/model/retrieval/tool/approval spans (verify qua OTel console/exporter test).
- Langfuse bật/tắt bằng env không đổi code; compose profile observability config hợp lệ.
- `make release-manifest` sinh manifest đúng schema; run mới liên kết manifest ref (integration test).
- Audit events đọc được qua API với authorization; append-only (không có UPDATE/DELETE path).
- CI workflow YAML validate; các job local-runnable chạy pass local (`make ci`).

### Tests phải chạy

Unit (graders, manifest builder, redaction), Integration (trace emission, eval runner, manifest-run linkage), Contract (event schemas), eval-smoke.

### Dependencies

Phase 3, 4 (cần 2 slice để eval).

### Risks

- Langfuse self-host nặng → chỉ nằm trong optional profile, không nằm trong default path.
- LLM-judge không có credential → mock judge + deterministic graders là chính; ghi rõ trong eval report.

### Definition of Done

Acceptance + quality gate pass, Progress cập nhật, commit phase 5.

---

## Phase 6 — Hardening, documentation và end-to-end acceptance

### Scope

- Hardening: rate limit/bulkhead per tenant, circuit breaker ở model gateway/connector, SSRF/URL allowlist cho fetch tool, secret redaction review, dependency audit fix, RLS review toàn bộ bảng, unknown-config-field fail ở production profile.
- UI hoàn thiện shell 10 routes (Home, Inbox, Knowledge, Memory, Integrations, Admin bổ sung), accessible approval components.
- Docs: `docs/threat-model/` (STRIDE tối thiểu cho tenant isolation, prompt injection, tool abuse, secret), `docs/runbooks/` (start/stop, migration rollback, stuck workflow recovery, tenant offboard), `docs/api/`, README final với exact commands + demo credentials, ADR set đầy đủ.
- Final acceptance (BƯỚC 4): chạy và ghi kết quả thật của toàn bộ lệnh:
  `make bootstrap/lint/typecheck/test-unit/test-integration/test-architecture/test-contract/eval-smoke`, `docker compose config`, `docker compose --profile full up --build -d`, `docker compose ps`, API health/ready, web load, blank-DB migration, seed idempotency (2 lần), 2 E2E workflow, approval pause/resume, cross-tenant (SQL + Qdrant), tool permission, audit, release manifest linkage, container healthy.
- Sửa mọi lỗi phát hiện trong acceptance; không báo pass khi command chưa chạy thật.

### Files/packages dự kiến

`docs/{threat-model,runbooks,api}/**`, `apps/web/**` (routes còn lại), hardening code rải theo package, README, `docs/implementation/ACCEPTANCE_REPORT.md` (bằng chứng command + output).

### Acceptance criteria

Toàn bộ checklist BƯỚC 4 của prompt + §29 blueprint pass, có bằng chứng output trong ACCEPTANCE_REPORT.md. Mục nào bị blocked bởi môi trường (ví dụ Docker chưa cài) phải ghi BLOCKED rõ ràng, không đánh pass.

### Tests phải chạy

`make ci` (toàn bộ), 2 E2E, compose smoke.

### Dependencies

Phase 0–5; **Docker Desktop phải được cài trên host trước phase này** (blocker đã ghi nhận).

### Risks

- Docker chưa được cài đúng hạn → toàn bộ mục container-based ở trạng thái BLOCKED; kế hoạch dự phòng: hoàn tất mọi mục non-container, bàn giao danh sách lệnh verify để chạy sau khi cài.
- Windows path/permission quirks trong container build → test build sớm ngay khi Docker sẵn sàng, không đợi Phase 6.

### Definition of Done

ACCEPTANCE_REPORT.md đầy đủ bằng chứng, mọi mục pass (hoặc BLOCKED có lý do môi trường được người dùng xác nhận), tag `v0.1.0`, release manifest sinh và commit.

---

## Progress

| Phase                                      | Trạng thái        | Ghi chú                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------------------ | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 — Bootstrap & Docker foundation          | DONE (2026-07-23) | Quality gate pass: ruff/mypy strict/70 unit tests/4 import-linter contracts/declared-deps 12 packages/TS typecheck 5 pkg/web build/`make ci` xanh. `docker compose config` CHƯA verify bằng CLI thật (B1) — YAML + healthcheck/non-root/multi-stage đã sanity-check bằng script.                                                                                                                                                                                                 |
| 1 — Kernel/tenancy/identity/authz          | DONE (2026-07-23) | 101 unit + 8 integration tests pass trên Docker Postgres: blank-DB migration + downgrade/upgrade roundtrip, RLS isolation/default-deny/cross-tenant-write-block, audit append-only (dw_app không UPDATE/DELETE), seed idempotent, membership lookup fail-closed, UoW SET LOCAL. Live smoke: /me 200 đúng context, cross-tenant 403, thiếu header 401. Blocker B1 RESOLVED — compose config 3 profile pass, 5/5 infra service healthy (minio healthcheck sửa dùng bash /dev/tcp). |
| 2 — Runtime/gateway/memory/knowledge/tools | NOT STARTED       |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 3 — Meeting-to-action slice                | NOT STARTED       |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 4 — Tender slice                           | NOT STARTED       |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 5 — Eval/observability/audit/release       | NOT STARTED       |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 6 — Hardening & acceptance                 | NOT STARTED       | Cần Docker Desktop trên host                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

## Blockers đang mở

| #   | Blocker                                              | Ảnh hưởng                                              | Hành động cần                                                        |
| --- | ---------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------- |
| B1  | Docker Desktop chưa cài trên host (cần admin + WSL2) | Integration/E2E container-based, compose smoke, BƯỚC 4 | Người dùng cài Docker Desktop; các phần khác vẫn tiến hành song song |
