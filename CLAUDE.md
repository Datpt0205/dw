# Claude Code Instructions — Digital Worker Platform

## Mission

Generate a production-shaped source base for a multi-tenant Digital Worker platform with two bounded contexts:

1. `tender`: Procurement Tender Digital Worker.
2. `work_ops`: Meeting-to-action and work coordination Digital Worker.

Use the architecture specification in `docs/architecture/Digital_Worker_Source_Base_Blueprint_v2.md` as the source of truth.

## Non-negotiable architecture

- One monorepo and one shared UI shell.
- Modular monolith plus separate async worker process for the initial release.
- Two independent bounded contexts; do not create a super-agent.
- Clean/Hexagonal dependency direction.
- Domain code must not import FastAPI, SQLAlchemy, LangGraph, Qdrant or provider SDKs.
- All external systems must be behind ports/adapters.
- PostgreSQL is the system of record.
- Qdrant retrieval must always receive trusted tenant/workspace/ACL filters from backend context.
- Redis/Valkey is not a source of truth.
- Side effects require policy evaluation, idempotency and audit; critical effects require approval.
- Every worker, graph, prompt, tool, policy, event schema and evaluation dataset is versioned.
- Human-in-command; POC autonomy level is A2 by default.

## Required stack

- Python 3.12, uv workspace.
- FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic.
- LangGraph adapter for workflow orchestration/checkpoint/HITL.
- PostgreSQL, Qdrant, Redis/Valkey, MinIO/S3.
- Next.js, TypeScript strict, Tailwind, shadcn/ui, CopilotKit.
- OpenTelemetry and optional Langfuse integration.
- Ruff, mypy or pyright, pytest, import-linter, pre-commit.
- pnpm workspace and lockfile.

Resolve compatible stable package versions and commit lockfiles. Do not use unpinned `latest` entries in production manifests.

## Work style

1. Inspect the repository before changing files.
2. Create an implementation plan and list assumptions.
3. Work in small phases; run tests after every phase.
4. Prefer a thin end-to-end vertical slice over many empty abstractions.
5. Never leave placeholder-only modules. A deferred component must have a working mock adapter and a documented port.
6. Keep diffs focused and update documentation with architecture-impacting changes.
7. Do not silently change the architecture. Create an ADR when deviating.

## Required repository structure

Create the exact top-level areas:

- `apps/api`
- `apps/worker`
- `apps/web`
- `packages/python/dw_kernel`
- `packages/python/dw_platform`
- `packages/python/dw_agent_runtime`
- `packages/python/dw_knowledge`
- `packages/python/dw_memory`
- `packages/python/dw_connectors`
- `packages/python/dw_tender`
- `packages/python/dw_work_ops`
- `packages/python/dw_observability`
- `packages/python/dw_evals`
- `packages/typescript/ui`
- `packages/typescript/api-client`
- `packages/typescript/contracts`
- `packages/typescript/agent-ui`
- `configs`, `contracts`, `db`, `evals`, `infra`, `scripts`, `docs`

## Python layer rules

For each bounded context:

- `domain`: entities, value objects, domain events, rules, domain services.
- `application`: commands, queries, handlers, ports, DTO mapping.
- `workflows`: versioned LangGraph state/graph/nodes/routing.
- `adapters`: persistence, external systems and provider implementations.
- `presentation`: API routes and event handlers.

Dependency direction:

- `application -> domain`
- `presentation -> application`
- `adapters -> application ports`
- only the composition root imports concrete adapters

Use constructor dependency injection. Do not use a service locator or mutable global client.

## Mandatory patterns

Use where applicable:

- Ports and Adapters.
- Repository and Unit of Work.
- Application command/query handlers.
- Strategy for model, retrieval, reranking and memory policy.
- Factory/Registry for workers, graphs, tools and connectors.
- Anti-Corruption Layer for Slack/Teams/ERP models.
- Transactional Outbox for external side effects.
- Specification/Policy objects for approval and authorization decisions.
- Idempotency, timeout, retry and circuit-breaker boundaries.

Do not create generic abstractions with no real variation or test seam.

## Tenant and authorization rules

- Every tenant-scoped table has `tenant_id` and `workspace_id`.
- Enable and test PostgreSQL RLS.
- Application runtime role must not bypass RLS.
- Set tenant context per transaction from verified server-side access context.
- Cache keys and object paths include tenant/workspace.
- Qdrant filter injection occurs only inside the knowledge gateway.
- Add negative tests for cross-tenant reads and writes.
- Entitlement checks and authorization checks are separate.

## Agent and tool rules

- One agentic workflow per bounded context in the POC.
- Graph state is typed and versioned.
- LLM output is always validated into a Pydantic schema.
- Workflow nodes must not contain provider SDK or SQL code.
- Tool definitions include version, schemas, scopes, side-effect level, approval policy, timeout and idempotency.
- Tool executor performs authorization, validation, execution, output validation and audit.
- All side effects use idempotency keys.
- Approval must pause and resume a durable/checkpointed run.

## Required vertical slices

### Work Operations

- Upload a transcript fixture.
- Normalize transcript.
- Produce typed summary, decisions and action candidates.
- Resolve assignee from seeded organization data.
- Create approval request.
- Approve in UI/API.
- Dispatch through `MockTaskConnector`.
- Persist external task reference and audit timeline.

### Tender

- Upload seeded tender/RFQ documents.
- Extract requirements into typed schema.
- Build compliance matrix.
- Apply deterministic weighted scoring.
- Produce recommendation with evidence references.
- Create approval request and export a simple evaluation pack.

## UI requirements

- Shared shell with routes for Home, Inbox, Approvals, Procurement, Work Ops, Knowledge, Memory, Integrations, Audit and Admin.
- Use CopilotKit as an adapter for agent interaction/HITL, not as the domain state store.
- Important outputs must have dedicated domain pages, not only chat messages.
- Generate the TypeScript API client from OpenAPI.
- Use strict TypeScript and runtime Zod validation.
- Never rely on hidden buttons as authorization.

## Observability and evaluation

Emit trace metadata for:

- tenant/workspace (safe identifiers only)
- worker and all artifact versions
- run/node/model/retrieval/tool/approval
- latency, token use and cost
- error taxonomy

Provide:

- OpenTelemetry instrumentation.
- Optional Langfuse adapter behind configuration.
- Golden dataset schema and smoke evals for both workers.
- Security evals for prompt injection, missing evidence and tenant leakage.

## Testing requirements

Create and run:

- unit tests
- architecture/import-boundary tests
- PostgreSQL repository/RLS integration tests
- Qdrant tenant-filter integration tests
- LangGraph checkpoint/resume tests
- outbox/idempotency tests
- API contract tests
- generated frontend client compile test
- two end-to-end vertical-slice tests
- eval smoke tests

## CI requirements

GitHub Actions must run:

1. config/contract validation
2. Python lint/format/typecheck
3. frontend lint/typecheck
4. unit tests
5. architecture tests
6. integration tests
7. security/dependency scan
8. eval smoke suite
9. container build
10. Docker Compose smoke test

Use reusable workflows where practical.

## Versioning requirements

Use SemVer and Conventional Commits. Generate an immutable release manifest containing:

- platform version and git SHA
- API version
- worker versions
- graph versions
- prompt bundle versions
- toolset versions
- policy versions
- knowledge index version
- evaluation dataset version

Persist the release manifest reference on every worker run.

## Required developer commands

Implement commands equivalent to:

- `make bootstrap`
- `make infra-up`
- `make migrate`
- `make seed`
- `make dev`
- `make lint`
- `make typecheck`
- `make test-unit`
- `make test-integration`
- `make test-architecture`
- `make test-eval-smoke`
- `make test-e2e`
- `make test-all`
- `make generate-contracts`
- `make release-manifest`

## Completion criteria

Do not declare completion until:

- blank database migrations pass
- seed is idempotent
- API/web/worker run locally
- both vertical slices pass end-to-end
- approval pause/resume works
- tenant isolation tests pass for SQL and Qdrant
- tool permission/idempotency tests pass
- traces and audit events are visible
- OpenAPI client generation passes
- CI is green
- README contains exact commands and demo credentials
- ADRs and threat model are present
