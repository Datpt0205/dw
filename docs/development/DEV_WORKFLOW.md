# Quy trình làm việc của dev với Claude Code

Trang này mô tả **vòng lặp hằng ngày**: setup → chuẩn bị prompt → rule cứng →
quality gate → commit. Nó không thay thế spec; nó chỉ gom những thứ đang nằm rải
rác ở `CLAUDE.md`, blueprint, `Makefile` và `ci.yml` vào một chỗ.

Prompt bootstrap Phase 0 nằm ở [`IMPLEMENTATION_PROMPT.md`](../../IMPLEMENTATION_PROMPT.md);
cách khởi động một máy trắng nằm ở [runbook local development](../runbooks/local-development.md).

## 1. Thứ tự đọc bắt buộc

1. [`CLAUDE.md`](../../CLAUDE.md) — quy tắc thực thi và các điều không được vi phạm.
2. [`docs/architecture/Digital_Worker_Source_Base_Blueprint_v2.md`](../architecture/Digital_Worker_Source_Base_Blueprint_v2.md) —
   đặc tả kiến trúc đầy đủ. Blueprint §28: tài liệu này là **specification, không
   phải gợi ý**.
3. Các ADR liên quan tới vùng code sắp đụng — xem [`docs/adr/`](../adr/).

Thứ tự phase thực tế **không theo §28** mà theo
[ADR-011](../adr/ADR-011-phase-mapping.md) (7 phase, UI xây dần theo từng vertical
slice). Đừng lấy §28 làm lịch trình.

## 2. Setup một lần

| Tool           | Phiên bản     | Ghi chú                          |
| -------------- | ------------- | -------------------------------- |
| uv             | ≥ 0.11        | CI pin `0.11.31`                 |
| Python         | 3.12          | uv tự quản lý                    |
| GNU make       | ≥ 4           | chạy trong Git Bash trên Windows |
| Node.js / pnpm | 22 LTS / ≥ 11 | `packageManager` pin pnpm 11.16  |
| Docker Desktop | mới nhất      | cần cho infra + integration test |

```bash
make bootstrap        # uv sync + pnpm install + cp .env.example .env + pre-commit install
#  → mở .env, đổi mọi giá trị change-me-*, chọn DW_MODEL_PROVIDER (mock là mặc định)
make infra-up         # Postgres/Qdrant/Valkey/MinIO/Keycloak, chờ healthy
make db-migrate
make db-seed          # idempotent
make dev              # API :8000 + worker + web :3000
```

`make bootstrap` đã cài pre-commit hook (ruff lint/format, secret scan, YAML/JSON
validation). Không bypass bằng `git commit --no-verify`.

## 3. Checklist trước khi gõ prompt

Chốt năm điều này trước, vì mỗi điều quyết định file nào được phép đụng:

1. **Bounded context** — `tender` hay `work_ops`. Hai context tuyệt đối không
   import nhau (import-linter có contract `independence`). Không gộp thành
   super-agent (ADR-002).
2. **Layer** — `domain` / `application` / `workflows` / `adapters` / `presentation`.
   Chiều phụ thuộc một hướng; chỉ composition root
   `apps/api/src/dw_api/bootstrap.py` được wire adapter thật (blueprint §26).
3. **Phase** theo ADR-011 — một phase một lần, không nhảy cóc.
4. **Artifact nào lên version** — worker / graph / prompt bundle / toolset /
   policy / eval dataset. Mọi thứ trong `configs/**` đều có version.
5. **Có side effect hoặc ranh giới bảo mật không** — nếu có thì phải kèm chuỗi
   policy → validation → idempotency → audit → approval (nếu critical), và phải
   có test cho ranh giới đó.

## 4. Khung prompt chuẩn

Dùng lại cấu trúc của `IMPLEMENTATION_PROMPT.md` cho **mọi** task, không chỉ
Phase 0:

- Nêu rõ tài liệu binding (`CLAUDE.md` + blueprint) và yêu cầu đọc trước khi sửa code.
- Yêu cầu **plan + assumptions + danh sách file dự kiến trước khi code**.
- Giới hạn phạm vi: một phase hoặc một vertical slice mỗi lần.
- Yêu cầu **chạy và báo cáo kết quả lint / typecheck / unit / architecture test
  sau mỗi phase**.
- Nhắc lại hai câu chốt:
    - “Không tạo placeholder package rỗng. Mọi external dependency deferred phải có
      typed port + mock adapter chạy được.”
    - “Mọi deviation kiến trúc phải có ADR.”

## 5. Rule cứng — vi phạm là hỏng kiến trúc

Đầy đủ ở blueprint §30 (14 điều cấm). Bốn điều hay bị vi phạm nhất:

| Rule                                                                                 | Test bắt được                                    |
| ------------------------------------------------------------------------------------ | ------------------------------------------------ |
| Domain không import FastAPI / SQLAlchemy / LangGraph / Qdrant / provider SDK         | `uv run lint-imports`                            |
| Package chỉ import cái nó khai báo trong pyproject của chính nó                      | `scripts/verify_architecture.py`                 |
| Tenant/ACL filter chỉ inject trong knowledge gateway, từ `AccessContext` server-side | integration test RLS + Qdrant tenant-filter test |
| Side effect critical phải qua approval, có idempotency key và audit                  | outbox/idempotency test, e2e slice test          |

Thêm: không lấy Redis/Valkey làm source of truth; không mock âm thầm ở production
profile; không swallow exception rồi trả success; không để prompt/config thiếu
version.

## 6. Quality gate sau khi Claude làm xong

Chạy theo đúng thứ tự này — rẻ trước, đắt sau:

```bash
make lint typecheck test-unit test-architecture   # vòng nhanh, luôn chạy
make generate-contracts     # NẾU đổi API — CI chạy --check, snapshot cũ là fail
make release-manifest       # NẾU đổi configs/** (worker/prompt/policy/tool/eval dataset)
make test-integration       # cần make infra-up
make ci                     # gate local đầy đủ, mirror CI trước khi push
```

CI (`.github/workflows/ci.yml`) chạy 10 stage theo blueprint §24.2, gồm cả
`pip-audit`, `pnpm audit --audit-level high`, eval smoke suite và Docker Compose
smoke test.

Commit theo [Conventional Commits](https://www.conventionalcommits.org/) và SemVer.

## 7. Bảy cái bẫy hay gặp

1. Sửa route API mà quên `make generate-contracts` → job `contracts` đỏ vì OpenAPI
   snapshot lệch.
2. Sửa `configs/prompts/*.yaml` (hoặc worker/policy/tool) mà quên
   `make release-manifest` → `release-manifest-check` đỏ.
3. Viết test mà quên marker (`unit` / `integration` / `contract` / `e2e` / `eval` /
   `architecture`) → `--strict-markers` fail, hoặc tệ hơn: test không bao giờ chạy.
4. Đổi password trong `.env` sau khi volume Postgres đã được tạo →
   `password authentication failed`. Phải `make infra-down` rồi
   `docker volume rm dw_postgres-data` (mất data local) và `make infra-up` lại.
5. Chạy `make db-seed` hoặc `make dev` khi chưa `make infra-up`.
6. Thêm abstraction không có variation thật (blueprint §25.3) — interface một
   method cho mọi class là over-engineering, không phải kiến trúc sạch.
7. Đổi quyết định kiến trúc mà không viết ADR. Blueprint §32 bắt buộc tối thiểu
   ADR-001…010; mọi deviation sau đó cần ADR mới.

## Liên kết

- [README — lệnh developer đầy đủ](../../README.md)
- [Runbook local development](../runbooks/local-development.md)
- [ADR-011 — phase mapping](../adr/ADR-011-phase-mapping.md)
- [Threat model (STRIDE)](../threat-model/THREAT_MODEL.md)
