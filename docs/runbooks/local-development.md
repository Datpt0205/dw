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

## Kênh chat Zalo (thay Slack — không nút bấm, duyệt bằng lời)

`.env`: điền `ZALO_BOT_TOKEN` (từ zalo.me/s/botcreator), đặt
`DW_APPROVAL_CHANNEL=zalo`, giữ `DW_CHAT_FRONT_OFFICE_ENABLED=true` và
`DW_SLACK_APPROVALS_ENABLED=true` (cờ bật hệ notification chung — không cần
token Slack). Mỗi người nhắn bot lần đầu sẽ được bot báo Zalo ID → điền vào
`ZALO_USER_AN_ID` / `ZALO_USER_BINH_ID` / `ZALO_USER_CHI_ID` rồi restart.

Toàn bộ thao tác bằng tiếng Việt tự nhiên:

| Việc | Nhắn |
| --- | --- |
| Khai intake | chat như thường (Ngọc hỏi gộp phần thiếu) |
| Xác nhận tạo hồ sơ | «đồng ý» (hoặc nhắn nội dung cần sửa) |
| Xác minh đầu vào (Bình) | «xác minh» / «từ chối» |
| Duyệt checkpoint | «duyệt cp1», «từ chối cp2»… |
| Chốt sổ mở thầu | «xác nhận mở thầu» |
| Lập sửa đổi (Bình) | «lập addendum gia hạn nộp thầu thêm 7 ngày» |
| Đổi hồ sơ đang nói tới | «chọn 1», «chọn 2» |

Đang khai dở mà đổi ý mua thứ khác («thôi, giờ cần mua 5 ghế») → bản nháp cũ
tự TẠM TREO, xong/huỷ yêu cầu mới sẽ tự quay lại đúng chỗ cũ.

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

## Đổi model provider (mock → OpenAI GPT-5)

Sửa `.env` (profile `openai` dùng /v1/responses — reasoning summary thật của
model làm dòng "Suy nghĩ", xem ADR-020):

```
DW_MODEL_PROVIDER=openai_compatible
OPENAI_API_KEY=<key>
OPENAI_BASE_URL=https://api.openai.com/v1
DW_API_OPENAI_STRUCTURED_MODE=json_schema
DW_API_MODEL_PROFILE=openai
```

Restart API. Production profile sẽ từ chối khởi động nếu chỉ có mock.

(DeepSeek cũ: `deepseek-chat`/`deepseek-reasoner` đã bị khai tử 24/07/2026 —
profile `deepseek` chỉ còn giá trị tham khảo, cần cập nhật model id V4 nếu
muốn dùng lại.)
