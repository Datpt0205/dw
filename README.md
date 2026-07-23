# Digital Worker Platform

Multi-tenant Digital Worker platform với hai bounded context độc lập:

- **`tender`** — Procurement Tender Digital Worker: phân tích RFQ/hồ sơ mời thầu, ma trận tuân thủ, chấm điểm deterministic, đề xuất kèm bằng chứng.
- **`work_ops`** — Meeting & Work Operations Digital Worker: transcript → tóm tắt → quyết định → action item → phê duyệt → giao việc.

Kiến trúc: modular monolith (API + async worker + web) trong một monorepo, Clean/Hexagonal, DDD, human-in-command (autonomy A2). Specification gốc: [docs/architecture/Digital_Worker_Source_Base_Blueprint_v2.md](docs/architecture/Digital_Worker_Source_Base_Blueprint_v2.md). Tiến độ triển khai: [docs/implementation/IMPLEMENTATION_PLAN.md](docs/implementation/IMPLEMENTATION_PLAN.md).

## Yêu cầu môi trường

| Tool           | Phiên bản            | Cài đặt (Windows)                                            |
| -------------- | -------------------- | ------------------------------------------------------------ |
| uv             | ≥ 0.11               | `winget install astral-sh.uv` hoặc `pip install uv`          |
| Python         | 3.12 (uv tự quản lý) | `uv python install 3.12`                                     |
| GNU make       | ≥ 4                  | `winget install ezwinports.make`                             |
| Node.js        | ≥ 22 LTS             | `winget install OpenJS.NodeJS.LTS`                           |
| pnpm           | ≥ 11                 | `npm install -g pnpm`                                        |
| Docker Desktop | mới nhất             | https://docs.docker.com/desktop/ (cần cho infra/integration) |

Chạy lệnh `make` trong **Git Bash** trên Windows.

## Bắt đầu nhanh

```bash
# 1. Cài dependency + tạo .env từ template
make bootstrap

# 2. Khởi động hạ tầng (Postgres, Qdrant, Valkey, MinIO, Keycloak)
make infra-up

# 3. Migration + seed demo (idempotent)
make db-migrate
make db-seed          # có từ Phase 1

# 4. Chạy API + worker + web trên host
make dev
```

Hoặc chạy **toàn bộ stack trong Docker**:

```bash
make docker-up        # profile full: infra + migrate job + api + worker + web
make docker-down
```

Langfuse (optional observability):

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml \
  --profile full --profile observability up -d --build
```

- API: http://localhost:8000 (docs: `/api/docs`, health: `/api/v1/health`, ready: `/api/v1/ready`)
- Web: http://localhost:3000
- Keycloak: http://localhost:8080 — MinIO console: http://localhost:9001 — Langfuse: http://localhost:3001

## Lệnh developer

```text
make bootstrap          Cài dependency Python + Node, tạo .env
make infra-up/-down     Bật/tắt data plane trong Docker
make dev                API + worker + web trên host (cần infra-up)
make docker-up/-down    Toàn bộ stack trong Docker (profile full)
make db-migrate | migrate    Alembic upgrade head
make db-seed    | seed       Seed demo idempotent (Phase 1)
make lint / format / typecheck
make test-unit / test-integration / test-architecture / test-contract / test-e2e
make eval-smoke | test-eval-smoke    Eval smoke suite (Phase 5)
make test-all
make generate-contracts  OpenAPI snapshot + TS client (Phase 3)
make release-manifest    Release manifest immutable (Phase 5)
make ci                  Toàn bộ quality gate local
```

## Cấu trúc monorepo

```text
apps/            api (FastAPI) · worker (async) · web (Next.js)
packages/python/ dw_kernel · dw_platform · dw_agent_runtime · dw_knowledge ·
                 dw_memory · dw_connectors · dw_tender · dw_work_ops ·
                 dw_observability · dw_evals
packages/typescript/ ui · contracts · api-client · agent-ui
configs/         worker/prompt/tool/model/plan/policy artifacts (versioned)
contracts/       openapi · events · tools · jsonschema
db/              alembic migrations · rls · seeds · fixtures
evals/           datasets · expected · graders · reports
infra/           compose · docker · helm · terraform
docs/            architecture · adr · runbooks · threat-model · implementation
```

## Quy tắc kiến trúc (enforced bằng test)

- Domain không import FastAPI/SQLAlchemy/LangGraph/Qdrant/provider SDK.
- `dw_tender` và `dw_work_ops` độc lập tuyệt đối.
- Mọi external system nằm sau port/adapter; chỉ composition root wire adapter thật.
- Qdrant retrieval luôn nhận tenant/ACL filter từ trusted `AccessContext` (không bao giờ từ model/client).
- Side effect: policy → validation → idempotency → audit → approval (nếu critical).

Chạy `make test-architecture` để kiểm tra. Chi tiết quyết định: [docs/adr/](docs/adr/).

## Demo credentials

Sẽ được bổ sung ở Phase 1 (seed 2 tenant + users + Keycloak realm).
