# Báo cáo nghiệm thu cuối (BƯỚC 4) — Digital Worker Platform

- **Ngày**: 2026-07-23
- **Máy**: Windows 11 + Docker Desktop (WSL2), Git Bash
- **Nguyên tắc**: mọi kết quả dưới đây là output của lệnh THẬT đã chạy — không có mục nào được đánh dấu pass mà chưa chạy.
- **Lưu ý (ảnh chụp thời điểm)**: báo cáo này chốt ở alembic head `0004`. Các thay đổi
  SAU đó (migration `0006` external_identities cho OIDC-register, `0007` DW01, `0008`/`0009`
  knowledge soft-delete + scope/ingest_jobs) làm các con số "29 bảng / head 0004" và mục
  auth "dev token" không còn khớp hiện trạng — auth mặc định nay là Keycloak OIDC.

## 1. Tổng quan kết quả

| Hạng mục (Completion criteria)           | Kết quả | Bằng chứng                                                                                                                                                                      |
| ---------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Blank database migration pass            | ✅      | `down -v` xoá volume → `up` → `make db-migrate`: 29 bảng / 6 schema, alembic head `0004`, **26 bảng RLS ENABLE+FORCE**                                                          |
| Seed idempotent                          | ✅      | `make db-seed` chạy 2 lần liên tiếp: cùng UUID (uuid5), sau 2 lần vẫn 5 users / 5 memberships / 3 roles — không trùng lặp                                                       |
| API + web + worker chạy local            | ✅      | `make dev` (các phase trước) và container mode (mục 4)                                                                                                                          |
| Hai vertical slice E2E pass              | ✅      | `pytest -m integration`: **28/28 pass** trên stack sạch (mục 2) + container-mode E2E (mục 4)                                                                                    |
| Approval pause/resume durable            | ✅      | E2E: run pause `waiting_approval` → approve → resume → `completed`; test checkpoint dựng lại toàn bộ runner stack giữa pause/resume vẫn resume đúng                             |
| Tenant isolation SQL + Qdrant            | ✅      | RLS tests (cross-tenant read/write bị chặn, default-deny); Qdrant: search đúng nguyên văn nội dung tenant khác → 0 kết quả; API cross-tenant → 404                              |
| Tool permission + idempotency            | ✅      | ToolExecutor tests: thiếu scope → deny + audit; replay cùng idempotency key → side effect không lặp; dispatch tool `approval_policy=always`                                     |
| Traces + audit visible                   | ✅      | Audit timeline đầy đủ `run.started → run.waiting_approval → run.resumed → run.completed` (assert trong E2E, xem được ở trang `/audit`); telemetry OTel + redaction có unit test |
| OpenAPI client generation pass           | ✅      | `make generate-contracts` + contract test snapshot; web build dùng types sinh ra — `pnpm --filter @dw/web build` pass (19 trang)                                                |
| Eval smoke pass                          | ✅      | `make eval-smoke`: tender 8/8 + work_ops 7/7, đủ security coverage (prompt_injection / cross_tenant_attack / missing_evidence)                                                  |
| Release manifest + gắn vào run           | ✅      | `make release-manifest` → `sha256:d116ee4bb5b1…`; mọi run mang `release_manifest_ref` (assert trong E2E ở cả 2 chế độ)                                                          |
| `make ci` xanh                           | ✅      | lint + format + mypy (222 files) + unit/contract (188) + import-linter 6 contracts + declared-deps 12 packages + eval smoke + manifest check                                    |
| Container build + compose full           | ✅      | 3 image build thành công, **8/8 container healthy** (mục 4)                                                                                                                     |
| README lệnh chính xác + demo credentials | ✅      | README.md (bảng user/tenant + luồng demo + observability)                                                                                                                       |
| ADRs + threat model                      | ✅      | ADR-001→017, `docs/threat-model/THREAT_MODEL.md` (STRIDE, mitigation → test), 4 runbooks                                                                                        |

## 2. Blank DB + integration suite trên stack sạch

```
docker compose --profile infra down -v        # xoá toàn bộ volume
docker compose --profile infra up -d --wait   # 5/5 service healthy
make db-migrate                               # blank DB → head 0004
  → 29 tables (platform/runtime/knowledge/memory/work_ops/tender)
  → 26 tables relrowsecurity AND relforcerowsecurity
make db-seed && make db-seed                  # 2 lần: 5 users, 5 memberships, 3 roles (không đổi)

uv run pytest -m integration                  # trên đúng stack sạch này
  → 28 passed  (RLS, membership fail-closed, checkpoint pause/resume qua
     restart, tool executor idempotency/permission, Qdrant tenant filter,
     memory policy, E2E work_ops 4 test, E2E tender 3 test)
```

## 3. Quality gate cuối (`make ci`)

```
ruff check + format --check          PASS (231 files)
mypy strict                          PASS (222 source files)
pytest -m unit                       PASS (186)
pytest -m contract                   PASS (2 — OpenAPI snapshot đồng bộ)
import-linter                        6 contracts KEPT
verify_architecture (declared deps)  PASS (12 packages)
eval smoke                           tender 8/8 · work_ops 7/7, security coverage ok
release_manifest --check             OK sha256:d116ee4bb5b1…
```

## 4. Container mode (docker compose --profile full)

Build phát hiện và sửa 3 lỗi thật (commit kèm báo cáo này):

1. Base image `ghcr.io/astral-sh/uv:0.11.31-python3.12-bookworm-slim` không tồn tại → builder đổi sang `python:3.12-slim-bookworm` + copy binary từ `ghcr.io/astral-sh/uv:0.11.31`.
2. Web image thiếu `tsconfig.base.json` trong build context.
3. Venv build tại `/build/.venv` nhưng chạy tại `/app/.venv` → shebang hỏng (`exec alembic: no such file`) → builder dùng thẳng `/app`; đồng thời API image ship `configs/`, `evals/fixtures/`, `contracts/release/` và đặt `DW_REPO_ROOT=/app`.

Kết quả cuối:

```
docker compose --profile full up -d --build --wait
dw-api-1        Up (healthy)      dw-migrate-1      Exited (0)  ← chạy alembic rồi thoát
dw-web-1        Up (healthy)      dw-minio-setup-1  Exited (0)
dw-worker-1     Up (healthy)      dw-postgres-1     Up (healthy)
dw-keycloak-1   Up (healthy)      dw-qdrant-1       Up (healthy)
dw-minio-1      Up (healthy)      dw-valkey-1       Up (healthy)

curl :8000/api/v1/health  → {"status":"ok","version":"0.1.0","api_version":"1.0"}
curl :8000/api/v1/ready   → {"status":"ready","checks":{"database":"ok"}}
curl :3000                → 307 (redirect về /home — web sống)
GET /api/v1/me (dev token + membership) → đúng principal, roles=[member],
  scopes đầy đủ, plan=professional
```

**E2E tender qua API container** (script smoke, mock model):

```
case created  → analyze 202 → run waiting_approval
release_manifest_ref = sha256:d116ee4bb5b1…      (gắn trên run)
golden scores: Thiết bị Việt 87.00 eligible · Vật tư Miền Nam disqualified
approve (dev|binh.tran) → run completed
evaluation pack: s3://dw-artifacts/<tenant>/<workspace>/exports/tender/<case>/evaluation_pack.json
audit: run.started → run.waiting_approval → run.resumed → run.completed
```

## 5. Bảo mật đã kiểm chứng bằng test

- Cross-tenant: SQL (RLS), API (404), Qdrant (0 kết quả) — 3 lớp độc lập.
- `SearchQuery` từ chối trường tenant do caller gửi (`extra="forbid"`); filter chỉ sinh trong `build_trusted_filter()`.
- Prompt injection bị giam trong block untrusted (eval case cả 2 worker).
- Mandatory không bằng chứng / quote bịa → fail closed (unit + eval + E2E).
- Audit append-only (dw_app bị REVOKE UPDATE/DELETE).
- Rate limit 429, circuit breaker, SSRF guard (chặn cả 169.254.169.254) — unit tests.
- Secret không nằm trong repo; production profile fail-fast với dev-auth/mock-model.

## 6. Điểm còn mở (ghi nhận, không chặn nghiệm thu POC)

- Rate limit per-process (multi-instance cần Redis) — ADR-017.
- Eval chất lượng model (model-backed grader) chạy ở nightly khi có key provider — ADR-015.
- GitHub Actions cần chạy trên runner có Docker để job integration/containers xanh (local tương đương đã pass toàn bộ).

**Kết luận: đạt toàn bộ completion criteria của CLAUDE.md — nghiệm thu PASS.**
