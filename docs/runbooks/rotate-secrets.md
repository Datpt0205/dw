# Runbook — Xoay secret

Nguyên tắc: secret chỉ tồn tại trong env/secret manager, không bao giờ trong
repo. `.env.example` chỉ chứa tên biến.

## DW_API_DEV_SECRET (dev token HS256)

1. Sinh secret mới ≥32 ký tự: `openssl rand -hex 32`.
2. Cập nhật `.env` (local) hoặc secret store (staging).
3. Restart API — mọi dev token cũ hết hiệu lực ngay (stateless).
4. Phát token mới: `uv run python scripts/issue_dev_token.py --subject "dev|<user>"`.

## OPENAI_API_KEY / DeepSeek key

1. Tạo key mới ở provider, cập nhật env, restart API/worker.
2. Thu hồi key cũ ở provider console.
3. Kiểm tra `dw_model_tokens_total` vẫn tăng (telemetry) hoặc chạy một
   analyze để xác nhận.

## MinIO root credentials

1. Đổi `MINIO_ROOT_USER/PASSWORD` trong secret store.
2. `docker compose ... up -d minio` rồi restart API (client đọc env mới).
3. Object cũ không cần re-encrypt (credential chỉ là access, không phải khóa mã hoá).

## Postgres roles (dw_app / dw_migrator)

1. `ALTER ROLE dw_app WITH PASSWORD '<new>';` bằng superuser.
2. Cập nhật `DW_API_DATABASE_URL` (+ worker) và `DW_MIGRATOR_DATABASE_URL`.
3. Rolling restart; kiểm tra `/api/v1/ready`.

## Keycloak client secret (oidc mode)

1. Regenerate trong Keycloak admin console (realm dw).
2. Cập nhật env web/API, restart.
3. Token cũ tự hết hạn theo TTL; không cần thu hồi tay.

## Langfuse keys

`LANGFUSE_PUBLIC_KEY/SECRET_KEY` — regenerate trong Langfuse project settings,
cập nhật env, restart API. Trace cũ không bị ảnh hưởng.
