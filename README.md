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
make db-seed    | seed       Seed demo idempotent
make lint / format / typecheck
make test-unit / test-integration / test-architecture / test-contract / test-e2e
make eval-smoke | test-eval-smoke    Eval suite: 15 case chấm safety gate thật
make test-all
make generate-contracts        OpenAPI snapshot + TS client
make release-manifest          Sinh release manifest immutable (content-addressed)
make release-manifest-check    Verify manifest khớp repo (chạy trong ci)
make ci                        Toàn bộ quality gate local (gồm eval + manifest)
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

## Đăng nhập & phân quyền (OIDC — mặc định)

Mặc định hệ thống chạy **Keycloak OIDC** (`DW_API_AUTH_MODE=oidc`,
`NEXT_PUBLIC_AUTH_MODE=oidc`). Mở web `http://localhost:3000` → màn hình đăng
nhập có **Đăng nhập** và **Đăng ký tài khoản mới** (ADR-019).

Tài khoản demo (realm import từ [infra/keycloak/dw-realm.json](infra/keycloak/dw-realm.json), mật khẩu `demo-password`):

| User Keycloak | Role trong workspace     | Thấy được gì trên UI                          |
| ------------- | ------------------------ | --------------------------------------------- |
| `an.nguyen`   | member                   | Đấu thầu, Cuộc họp, Phê duyệt (không duyệt được) |
| `binh.tran`   | approver, member         | + nút Phê duyệt/Từ chối                        |
| `chi.le`      | platform_admin, member   | + link **Quản trị** (bỏ qua mọi kiểm tra scope) |

**Đăng ký:** bấm «Đăng ký tài khoản mới» → tạo tài khoản trong Keycloak → lần
đăng nhập đầu, tài khoản được **lưu thật vào Postgres** (`platform.users` +
`external_identities` + `memberships`) và tự vào workspace demo **Công ty Alpha**
với vai **member**. Nâng/hạ vai trò do quản trị viên thao tác (bước sau).

UI ẩn/khoá theo `scope` cho gọn, nhưng **backend là nơi enforce duy nhất** —
mọi request đều được xác minh token + membership trong DB (cross-tenant/không đủ
quyền → 403).

Sau `make db-seed` cũng có 2 tenant + 5 user dùng cho **dev mode** và API test
qua dev token (`scripts/issue_dev_token.py`, ADR-013). Bật dev mode bằng
`DW_API_AUTH_MODE=dev` + `NEXT_PUBLIC_AUTH_MODE=dev` (trang `/dev-login`).

## Luồng demo end-to-end

Mở web → **Đăng nhập** bằng `an.nguyen` / `demo-password` (hoặc «Đăng ký» tài khoản mới).

1. **Đấu thầu** (`/tender`): «Tạo hồ sơ mẫu» → «Phân tích hồ sơ» → ma trận
   tuân thủ + điểm deterministic (Thiết bị Việt 87.00 thắng; Vật tư Miền Nam
   bị loại vì giao hàng 45>30 ngày) → Phê duyệt (đổi vai `Trần Thanh Bình`)
   → evaluation pack xuất vào MinIO.
2. **Cuộc họp** (`/meetings`): «Tạo cuộc họp mẫu» → «Sinh action items» →
   tóm tắt + **phân tích chất lượng họp** (điểm /10, tốt/chưa tốt kèm trích
   dẫn) + action items → Phê duyệt → dispatch qua connector (mock hoặc
   Slack thật qua `DW_TASK_CONNECTOR=slack`).
3. **Bot Telegram**: điền `TELEGRAM_BOT_TOKEN` vào `.env`, nhắn `/start` cho
   bot để lấy ID rồi map trong `configs/demo/channel_identities.yaml`; gửi
   transcript cho bot → nhận phân tích qua chat.
4. Trang hệ thống (link cuối sidebar/Trang chủ): `/audit`, `/knowledge`,
   `/memory`, `/integrations`; run detail có `release_manifest_ref`.

## Observability (optional)

```bash
# OTLP collector bất kỳ
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces

# hoặc Langfuse (profile observability của compose)
LANGFUSE_ENABLED=true
LANGFUSE_HOST=http://localhost:3001
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
```

Span/metric chỉ chứa safe identifier (worker, version, tenant id, token
count) — không bao giờ chứa prompt content; mọi attribute qua redaction.

## Tài liệu vận hành & bảo mật

- [Threat model (STRIDE)](docs/threat-model/THREAT_MODEL.md)
- [Runbooks](docs/runbooks/): local dev · approval kẹt · sự cố cách ly tenant · xoay secret
- [ADRs](docs/adr/) — ADR-015 evals, ADR-016 observability, ADR-017 hardening
- [Báo cáo nghiệm thu](docs/implementation/ACCEPTANCE_REPORT.md)
