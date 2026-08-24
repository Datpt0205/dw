# dw-lab — sandbox thử lõi deepagents

Bản sao của `../dw` (branch `lab/deepagents`) để thử `deepagents` làm lõi agent
mà không đụng bản demo đang chạy. **Không phải môi trường thật. Đừng deploy.**

## Cách ly đang có

| Thứ | `dw` (đang chạy) | `dw-lab` |
|---|---|---|
| Process | full stack trong Docker | Python chạy trên host |
| Database | `dw` | `dw_lab` |
| DB test | `dw_test`, `dw_test_runtime` | `dw_lab_test`, `dw_lab_test_runtime` |
| API port | 8000 | 8100 |
| Web port | 3000 | (chưa cài, dùng 3100 nếu cần) |
| Qdrant collection | `dw_knowledge` | `dw_knowledge_lab` |
| MinIO bucket | `dw-artifacts` / `dw-exports` | `dw-lab-artifacts` / `dw-lab-exports` |
| Valkey DB | `redis://…/0` | `redis://…/5` |
| Auth | Keycloak OIDC (:8686) | `dev` mode, `POST /api/v1/dev/session` |
| Compose project | `dw` | `dw-lab` (chỉ là chốt an toàn — lab KHÔNG chạy compose) |
| Kênh ra ngoài | Slack + Zalo + Telegram + SMTP/IMAP **thật** | **tắt sạch, token để rỗng** |

Container hạ tầng (Postgres/Qdrant/Valkey/MinIO/TEI/Keycloak) thì **dùng chung** —
máy chỉ có 7.8Gi RAM và swap thường xuyên đầy, không đủ cho stack thứ hai.

## `dw-lab-pgproxy` — tại sao có container này

`dw-postgres-1` **không** publish 5432 ra host (host 5432 là một Postgres khác,
không có role `dw_migrator`). Bản `dw` không vướng vì nó chạy full trong Docker
và nối qua service name. Lab chạy trên host nên cần một đường vào:

```bash
docker run -d --name dw-lab-pgproxy --network dw_dw-edge \
  --restart unless-stopped --label dw.lab=true \
  -p 127.0.0.1:15432:5432 alpine/socat:latest \
  tcp-listen:5432,fork,reuseaddr tcp-connect:postgres:5432
```

Container này chỉ thêm vào, không sửa gì của stack `dw`, xoá lúc nào cũng được.
Nếu `dw-postgres-1` bị recreate, chạy lại `docker restart dw-lab-pgproxy`.

## Runbook

```bash
cd /home/congnt/FPT_Digital/dw-lab

uv sync --all-packages          # môi trường Python riêng
make db-migrate                 # -> dw_lab
make db-seed                    # -> dw_lab

uv run pytest -m unit           # 275 passed
make test-architecture          # 6 contracts + declared-deps
uv run mypy                     # strict

# API lab
set -a && source .env && set +a
uv run uvicorn dw_api.main:app --host 127.0.0.1 --port 8100

# Token để gọi API (không cần browser/Keycloak)
TOKEN=$(curl -s -X POST localhost:8100/api/v1/dev/session \
  -H 'content-type: application/json' -d '{"subject":"dev|chi.le"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "authorization: Bearer $TOKEN" \
     -H "X-Tenant-Id: d6b43d0e-c3c6-5dbc-bc08-150621bd9a5d" \
     -H "X-Workspace-Id: 64764894-718d-5558-ba17-9a2949214063" \
     localhost:8100/api/v1/me
```

## Guardrails

- **Không** `make infra-up` / `make docker-up` trong thư mục này. Compose hardcode
  port 3000/8000/6333/9000/8085/8086 → xung đột, và `tei-embed` sẽ ăn nốt RAM còn lại.
  `COMPOSE_PROJECT_NAME=dw-lab` là chốt: một lệnh `make docker-down` gõ lạc ở đây
  **không** hạ được stack `dw`.
- **Không bao giờ** `docker compose down -v` ở cả hai repo — `-v` xoá volume, mất
  sạch dữ liệu demo.
- Trước khi migrate/seed, kiểm tra đích: `grep '^DW_DATABASE_URL=' .env | tail -1`
  phải kết thúc bằng `/dw_lab`.
- Đừng bật lại token Slack/Zalo/Telegram/IMAP trong `.env` của lab. Hai poller cùng
  một bot token sẽ giành update của nhau và phá bản demo đang chạy (Telegram trả
  thẳng `409 Conflict`).
- `.env` nằm trong `.gitignore` — đừng `git add -f`.
- `release-manifest` sinh ở đây khác bản `dw`; đừng copy ngược.

## Teardown

```bash
docker rm -f dw-lab-pgproxy
docker exec -i dw-postgres-1 psql -U dw_admin -d postgres \
  -c 'DROP DATABASE IF EXISTS dw_lab;' \
  -c 'DROP DATABASE IF EXISTS dw_lab_test;' \
  -c 'DROP DATABASE IF EXISTS dw_lab_test_runtime;'
curl -X DELETE localhost:6333/collections/dw_knowledge_lab
docker exec dw-valkey-1 valkey-cli -n 5 flushdb
docker exec dw-minio-1 sh -c 'mc alias set lab http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" && mc rb --force lab/dw-lab-artifacts lab/dw-lab-exports'
rm -rf /home/congnt/FPT_Digital/dw-lab
```

## Trạng thái lõi deepagents

`deepagents 0.7.8` + `langchain-openai 1.6.0` đã nằm trong `dw-agent-runtime`.
Seam ở `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/deepagents_graph.py`.

**Ý chính:** `create_deep_agent()` trả về graph *đã* compile, còn
`LangGraphWorkflowRunner._graph()` thì gọi `factory().compile(checkpointer=...)`.
`DeepAgentGraphSpec` khớp đúng hai hình dạng đó, nên **không phải sửa một dòng nào**
của runner, `GraphRegistry`, `SqlAlchemyCheckpointSaver`, run store, mapping
interrupt→ApprovalRequest hay telemetry.

Đã chứng minh chạy được (`pytest packages/python/dw_agent_runtime/tests/integration/test_deepagents_seam.py`):

1. `spec.compile(checkpointer=SqlAlchemyCheckpointSaver)` → `CompiledStateGraph`;
2. `interrupt_on={"send_rfq": True}` làm agent dừng → `state["__interrupt__"]`;
3. state của deep agent ghi thật vào `platform.run_checkpoints` theo tenant (RLS);
4. resume sau khi duyệt thì chạy nốt, hết interrupt.

**Khoảng hở duy nhất còn lại — hình dạng payload resume:**

| | payload |
|---|---|
| `ApproveAndResumeService` đang gửi | `{"approved": bool, "comment": str, "approved_action_ids"?: [...]}` |
| HITL middleware của deepagents chờ | `{"decisions": [{"type": "approve"｜"edit"｜"reject"｜"respond"}]}` |

Cần một lớp dịch (ở `DeepAgentGraphSpec` hoặc một `WorkflowRunnerPort` riêng)
trước khi lõi này dùng được với luồng duyệt thật. Payload của interrupt cũng khác
`demo_graph`: deepagents trả `{"action_requests": [...], "review_configs": [...]}`,
nên card duyệt trên Slack/Zalo sẽ cần đọc theo khuôn mới.

**Chưa làm (là quyết định thiết kế của bạn, không phải việc cơ khí):** đăng ký một
worker thật chạy lõi deepagents. Cách làm: `graph_registry.register(worker_id,
"<version>-deepagents", lambda: DeepAgentGraphSpec(...))` trong `bootstrap.py` cộng
một file `configs/workers/<worker>@<version>-deepagents.yaml`. Dùng `graph_version`
mới chứ đừng thay cái cũ — `GraphRegistry.register` raise khi trùng key, và giữ cả
hai thì bật/tắt lõi mới bằng `worker_version` để so A/B trên cùng DB.

**Lệch kiến trúc có ý thức:** deepagents nhận `BaseChatModel` của LangChain, nên nó
đi vòng qua port `ModelGateway`. `chat_model_from_route()` dựng model từ chính
`configs/models/*.yaml` để hai lõi cùng model, nhưng đưa về `dw` thì cần ADR
(CLAUDE.md: "Do not silently change the architecture").
