# Chạy stack — sổ tay lệnh

Mọi lệnh dưới đây chạy từ **gốc repo**: `/home/congnt/FPT_Digital/dw`.

---

## 0. Ba điều phải biết trước

**`docker compose up -d --build` trần sẽ KHÔNG chạy được.** Ba lý do:

1. **Không có compose file ở gốc repo.** Nó nằm ở `infra/compose/docker-compose.yml`
   → lệnh trần báo `no configuration file provided: not found`.
2. **Mọi service đều nằm sau profile** (`infra` / `full` / `models` / `observability`).
   Kể cả khi trỏ đúng `-f`, `up` trần khởi động **0 container**.
3. **`.env` không tự nạp.** Compose lấy thư mục chứa file `-f` làm project directory,
   nên nó tìm `infra/compose/.env` chứ không phải `.env` ở gốc → lỗi
   `required variable MINIO_ROOT_USER is missing a value`.

> ⚠️ Lý do 3 có bẫy ngầm nguy hiểm hơn cả lỗi: `COMPOSE_PROJECT_NAME=dw` **cũng nằm
> trong `.env`**. Thiếu `--env-file .env`, project name rơi về `compose` → Docker tạo
> bộ volume `compose_postgres-data` mới tinh và **toàn bộ DB trong `dw_postgres-data`
> biến mất khỏi tầm nhìn của stack**. Không mất dữ liệu thật, nhưng đủ để hoảng.

**Đừng `cd` vào `infra/compose`.** Build context là `../..` nên vẫn build được, nhưng
`--env-file` sẽ phải viết thành `../../.env` — dễ quên hơn nữa.

**Cách an toàn nhất: dùng `make`.** Makefile đã gói sẵn `--env-file`, profile và
overlay GPU.

---

## 1. Lệnh dùng hàng ngày

| Việc cần làm                          | Lệnh               |
| ------------------------------------- | ------------------ |
| Bật **toàn bộ** stack (13 service)    | `make docker-up`   |
| Tắt toàn bộ (giữ dữ liệu)             | `make docker-down` |
| Chỉ bật hạ tầng (chạy code trên host) | `make infra-up`    |
| Tắt hạ tầng                           | `make infra-down`  |
| Xem trạng thái                        | xem §3             |
| Xem log                               | xem §8             |

Sau `make docker-up`, mở **http://localhost:3000**, đăng nhập `chi` / `demo`.

---

## 2. Bản `docker compose` thuần (khi cần lệnh chi tiết)

Đặt một biến tắt cho cả phiên terminal:

```bash
cd /home/congnt/FPT_Digital/dw

export DC="docker compose --env-file .env \
  -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.gpu.yml"
```

> Bỏ dòng `-f ...gpu.yml` nếu máy **không** có GPU Turing trở lên (compute ≥ 7.5).
> Máy hiện tại đang bật `DW_GPU=1` trong `.env` nên `make` tự thêm overlay này.

Rồi:

```bash
$DC --profile full up --build -d      # bật + build
$DC --profile full ps                 # trạng thái
$DC --profile full down               # tắt, giữ volume
```

---

## 3. Kiểm tra stack đã lên chưa

```bash
$DC --profile full ps
curl -fsS http://127.0.0.1:8000/api/v1/health
```

Kỳ vọng: **13 service**, trong đó `api` / `worker` / `web` / `postgres` / `qdrant` /
`valkey` / `minio` / `keycloak` / `tei-embed` / `tei-rerank` đang **running**, còn
`migrate` / `seed` / `minio-setup` ở trạng thái **exited (0)** — đó là các job chạy
một lần rồi thoát, **không phải lỗi**.

---

## 4. Cổng và URL

| Service            | URL                             | Ghi chú                                                          |
| ------------------ | ------------------------------- | ---------------------------------------------------------------- |
| Web (Next.js)      | http://localhost:3000           | giao diện chính                                                  |
| API (FastAPI)      | http://localhost:8000           | health: `/api/v1/health`, docs: `/api/docs`                      |
| Keycloak           | http://localhost:8686           | admin: `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` trong `.env` |
| Qdrant             | http://localhost:6333/dashboard | vector store                                                     |
| MinIO console      | http://localhost:9001           | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`                        |
| MinIO S3 API       | http://localhost:9000           |                                                                  |
| Postgres           | `localhost:5432`                | đổi qua `POSTGRES_HOST_PORT` trong `.env` nếu cổng bận           |
| Valkey (Redis)     | `localhost:6379`                |                                                                  |
| TEI embed (BGE-M3) | http://localhost:8085           |                                                                  |
| TEI rerank         | http://localhost:8086           |                                                                  |
| Langfuse           | http://localhost:3001           | chỉ có ở profile `observability`                                 |

Tất cả đều bind vào `127.0.0.1` — không lộ ra mạng LAN.

---

## 5. Tài khoản demo

| User        | Mật khẩu | Vai                                   |
| ----------- | -------- | ------------------------------------- |
| `chi`       | `demo`   | trưởng ban — **duyệt** mọi checkpoint |
| `an.nguyen` | `demo`   | người đề nghị — không có quyền duyệt  |
| `binh.tran` | `demo`   |                                       |

---

## 6. Bốn profile

| Profile         | Gồm gì                                                 | Dùng khi                      |
| --------------- | ------------------------------------------------------ | ----------------------------- |
| `infra`         | Postgres, Qdrant, Valkey, MinIO, Keycloak              | chạy api/worker/web trên host |
| `full`          | `infra` + TEI ×2 + migrate + seed + api + worker + web | chạy tất cả trong Docker      |
| `models`        | chỉ tei-embed + tei-rerank                             | tải model trước cho đỡ nghẽn  |
| `observability` | Langfuse + ClickHouse                                  | khi cần xem trace             |

Ghép được: `$DC --profile full --profile observability up -d`

---

## 7. Lần đầu trên máy mới

```bash
make bootstrap          # uv sync + pnpm install + tạo .env từ .env.example
# → mở .env, điền OPENAI_API_KEY, OPENAI_BASE_URL, các mật khẩu change-me-*

# Tải model TEI trước (lần đầu ~4.3GB, có thể mất 30 phút)
$DC --profile models up -d
$DC logs -f tei-embed tei-rerank      # chờ tới khi cả hai healthy

make docker-up
```

**Lần đầu TEI hay bị đánh dấu `unhealthy`** vì healthcheck hết lượt thử trong lúc
model vẫn đang tải. Container **vẫn chạy** và sẽ tự chuyển sang healthy sau đó — cứ để
yên, đừng restart.

Nếu máy không passthrough được GPU: đặt `DW_API_EMBEDDING_PROVIDER=hash` trong `.env`
để bỏ qua TEI (RAG kém chính xác hơn nhưng stack chạy đủ để demo).

---

## 8. Chạy lai (code trên host, hạ tầng trong Docker)

```bash
make infra-up
make migrate
make seed
make dev          # chạy song song api + worker + web, Ctrl-C để dừng cả ba
```

---

## 9. Sau khi sửa `.env` hoặc sửa code

```bash
# sửa .env → nạp lại biến môi trường
$DC --profile full up -d --force-recreate api worker

# sửa code Python/TS → build lại image
$DC --profile full up -d --build api worker web
```

---

## 10. Log, shell, database

```bash
$DC logs -f api                          # theo dõi log API
$DC logs --tail=200 worker               # 200 dòng cuối của worker
$DC logs api | grep -iE "error|openai"   # lọc

$DC exec api bash                        # vào shell container

# psql (POSTGRES_USER lấy từ .env, mặc định dw_admin)
$DC exec -T postgres psql -U dw_admin -d dw
$DC exec -T postgres psql -U dw_admin -d dw -c '\dn'   # liệt kê schema
```

---

## 11. Reset dữ liệu demo

```bash
bash scripts/demo_reset.sh        # xoá hồ sơ DW01 + ngữ cảnh chat, GIỮ user/knowledge/audit
bash scripts/seed_demo_cases.sh   # dựng lại 4 hồ sơ "hàng xóm" (idempotent)
```

Kịch bản demo Zalo 16 câu: `docs/runbooks/demo-script.md`.
Teleprompter: `powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1`

---

## 12. Bẫy đã gặp thật

| Hiện tượng                                                                               | Nguyên nhân                                                                                                                                                                                           | Xử lý                                                                                                                                                                                                                                                        |
| ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| ~~`make docker-up` / `make infra-up` báo `Error 1` dù stack lên bình thường~~ **ĐÃ SỬA** | `up --wait` coi container one-shot thoát code 0 là thất bại — trừ khi có service khác khai báo nó là `service_completed_successfully`. `migrate`/`seed` có, `minio-setup` thì **không ai depends_on** | `api`+`worker` giờ khai báo `minio-setup: service_completed_successfully` (vốn là phụ thuộc thật — chúng ghi vào bucket S3 do nó tạo). Profile `infra` không có api/worker nên `infra-up` tách làm 2 bước: `up -d` rồi `up -d --wait` với 5 service chạy dài |
| `no configuration file provided: not found`                                              | chạy `docker compose` trần                                                                                                                                                                            | §0                                                                                                                                                                                                                                                           |
| `required variable MINIO_ROOT_USER is missing a value`                                   | thiếu `--env-file .env`                                                                                                                                                                               | §0                                                                                                                                                                                                                                                           |
| Volume mới toanh, DB trống trơn                                                          | thiếu `--env-file .env` → mất `COMPOSE_PROJECT_NAME=dw`                                                                                                                                               | §0                                                                                                                                                                                                                                                           |
| `password authentication failed for user "dw_migrator"`                                  | đổi mật khẩu trong `.env` nhưng volume Postgres cũ vẫn giữ mật khẩu cũ                                                                                                                                | `ALTER ROLE ... WITH PASSWORD` trong psql, **hoặc** `$DC --profile full down -v` (mất sạch data)                                                                                                                                                             |
| Port 5432 đã bận                                                                         | Postgres khác đang chạy trên host                                                                                                                                                                     | đặt `POSTGRES_HOST_PORT=5433` trong `.env`                                                                                                                                                                                                                   |
| TEI `unhealthy` lần đầu                                                                  | đang tải ~4.3GB model                                                                                                                                                                                 | chờ, đừng restart (§7)                                                                                                                                                                                                                                       |
| `telegram poll error ... 409 Conflict` lặp vô hạn                                        | `TELEGRAM_BOT_TOKEN` còn trong `.env`, có consumer khác giữ hàng đợi                                                                                                                                  | xoá giá trị đó rồi `--force-recreate api`                                                                                                                                                                                                                    |
| `make help` in ra chữ "Makefile"                                                         | `include .env` đẩy `.env` vào `MAKEFILE_LIST`                                                                                                                                                         | lỗi đã biết, chưa sửa                                                                                                                                                                                                                                        |

---

## 13. Dọn sạch

```bash
make docker-down                      # tắt, GIỮ volume (dữ liệu còn nguyên)
$DC --profile full down -v            # tắt + XOÁ HẾT volume — mất toàn bộ DB
docker volume ls | grep dw_           # kiểm tra volume còn lại
```
