# Claude Code Bootstrap Prompt

```text
Read CLAUDE.md and docs/architecture/Digital_Worker_Source_Base_Blueprint_v2.md completely before editing code.
The documents are binding. Do not silently replace architectural decisions.

Goal: create a production-shaped, locally runnable source base for a multi-tenant Digital Worker platform with two independent bounded contexts: tender and work_ops.

Execution rules:
- Work phase by phase.
- Start with Phase 0 only.
- Show assumptions, planned files and acceptance criteria before implementation.
- Run and report lint, type checks, unit tests and architecture tests after each phase.
- Prefer an executable vertical slice over broad placeholder abstractions.
- Any deviation requires an ADR.
- Do not expose provider SDKs to domain/application code.
- Do not trust tenant, ACL or tool permissions supplied by model output or client payload.
- Critical side effects require approval, idempotency and audit.

Phase 0 deliverables:
1. Monorepo and uv/pnpm workspaces.
2. Exact top-level package structure required by CLAUDE.md.
3. Python and TypeScript quality configuration.
4. Docker Compose for PostgreSQL, Qdrant, Redis/Valkey, MinIO and Keycloak.
5. Config profiles and `.env.example` without secrets.
6. Makefile or Taskfile with executable commands.
7. Boundary tests using import-linter or an equivalent architecture-test mechanism.
8. README and ADR-001 through ADR-004.
9. CI workflow for lint, type check and unit/architecture tests.
10. Passing `make bootstrap`, `make lint`, `make typecheck`, `make test-unit`, and `make test-architecture`.

Stop after Phase 0, summarize files changed and provide exact commands/results. Wait for review before Phase 1.
```
