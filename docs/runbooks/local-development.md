# Runbook — Local development

## Khởi động từ máy trắng

```bash
make bootstrap        # uv sync + pnpm install + copy .env.example → .env
make infra-up         # Postgres, Qdrant, Valkey, MinIO, Keycloak (đợi healthy)
make db-migrate       # alembic upgrade head (chạy bằng role dw_migrator)
make db-seed          # seed idempotent: roles/plans/2 tenant/users/fixtures
make dev              # API :8000 + web :3000 (mock model mặc định)
```

Đăng nhập: mặc định là **Keycloak OIDC** (Authorization Code + PKCE) tại
`http://localhost:3000` — hỗ trợ **login, logout và tự đăng ký** (tài khoản mới
được auto-provision vào tenant demo với role `member`). Chế độ dev
(`DW_API_AUTH_MODE=dev`) thay bằng trang một-cú-nhấp `/dev-login` để chọn nhanh
một user roster (không cần Keycloak).

## Chạy full stack trong Docker

```bash
make docker-up        # compose --profile full up --build (API+worker+web+infra)
docker compose --env-file .env -f infra/compose/docker-compose.yml --profile full ps
make docker-down
```

## Khi Postgres không lên

1. `docker logs dw-postgres-1 --tail 50` — thường do volume cũ khác password.
2. Xoá sạch state (MẤT DATA local): `make infra-down` rồi
   `docker volume rm dw_postgres-data` và `make infra-up` lại.

## Khi integration test fail hàng loạt

- Test harness tự recreate `dw_test`/`dw_test_runtime` — cần `make infra-up`
  đang chạy và `.env` đúng port mặc định.
- Lỗi `password authentication failed` → volume Postgres tạo từ .env cũ; xem mục trên.

## Đổi model provider (mock → DeepSeek/OpenAI)

Sửa `.env`:

```
DW_MODEL_PROVIDER=openai_compatible
OPENAI_API_KEY=<key>
OPENAI_BASE_URL=https://api.deepseek.com/v1
DW_API_OPENAI_STRUCTURED_MODE=json_object   # DeepSeek chưa có json_schema
DW_MODEL_PROFILE_ID=deepseek
```

Restart API. Production profile sẽ từ chối khởi động nếu chỉ có mock.
