# Thiết lập Slack thật cho luồng phê duyệt DW01

## Luồng đã được triển khai

```text
An tạo case
  -> PostgreSQL ghi case + lịch DM Bình + lịch escalation Chi
  -> worker gửi DM Bình ngay
  -> sau 5 giây worker đọc lại state
       -> còn draft: DM Chi
       -> đã duyệt/từ chối: huỷ escalation
  -> Bình mở link, đăng nhập tài khoản approver
       -> duyệt: DM An báo đã duyệt
       -> từ chối: bắt buộc lý do, DM An kèm lý do
```

Slack chỉ là kênh giao tiếp. PostgreSQL là nguồn sự thật về trạng thái. Worker có
retry/backoff, job idempotency, lịch sử số lần gửi và không dùng `sleep(5)` trong
API. Mốc 5 giây là cấu hình demo; khi vận hành thật phải thay bằng SLA nghiệp vụ.

Phiên bản hiện tại dùng nút **Mở hồ sơ DW01** trong Slack. Quyết định được thực hiện
trên web sau khi đăng nhập tài khoản Bình, nên không cần public callback, Signing
Secret, Event Subscriptions hay Socket Mode.

## 1. Tạo Slack App

1. Mở <https://api.slack.com/apps>.
2. Chọn **Create New App**.
3. Chọn **From scratch**.
4. App Name: `DW Procurement`.
5. Chọn đúng workspace có tài khoản Slack của An, Bình và Chi.
6. Chọn **Create App**.

Không tạo Incoming Webhook. Hệ thống dùng Slack Web API và bot token.

## 2. Cấp đúng hai quyền tối thiểu

1. Trong menu trái, mở **OAuth & Permissions**.
2. Tìm **Scopes** > **Bot Token Scopes**.
3. Chọn **Add an OAuth Scope**, tìm và thêm `chat:write`.
4. Chọn **Add an OAuth Scope** lần nữa, tìm và thêm `im:write`.
   - `chat:write`: bot gửi Block Kit message.
   - `im:write`: bot mở DM với người nhận bằng `conversations.open`.
5. Để trống toàn bộ mục **User Token Scopes**.
6. Không cần `users:read`, `users:read.email`, `channels:read` hoặc
   `chat:write.public` cho luồng DM hiện tại.

Ở giao diện Slack hiện tại, nút **Install to Workspace** bị vô hiệu hoá cho đến
khi có ít nhất một scope. Luồng này không dùng OAuth callback nên không cần điền
**Redirect URLs**, không bật **Token Rotation**, **PKCE**, **Socket Mode**,
**Incoming Webhooks** hoặc **Interactivity**.

Nếu thay đổi scope sau khi đã cài app, phải chọn **Reinstall to Workspace**.

## 3. Cài app và lấy Bot User OAuth Token

1. Vẫn trong **OAuth & Permissions**, chọn **Install to Workspace**.
2. Chọn **Allow**.
3. Trở lại mục **OAuth Tokens for Your Workspace**.
4. Sao chép **Bot User OAuth Token**, bắt đầu bằng `xoxb-`.
5. Không gửi token qua chat, email hoặc commit Git.

Giá trị này sẽ đặt vào:

```env
SLACK_BOT_TOKEN=xoxb-...
```

Không lấy User OAuth Token (`xoxp-...`) và không lấy App-Level Token (`xapp-...`).

## 4. Lấy Member ID của An, Bình và Chi

Lặp lại cho từng người:

1. Mở Slack desktop hoặc web.
2. Nhấp tên/avatar người dùng để mở profile.
3. Chọn dấu ba chấm **More**.
4. Chọn **Copy member ID**.
5. Giá trị hợp lệ thường bắt đầu bằng `U` (đôi khi `W` trên Enterprise Grid).

Điền đúng mapping:

```env
SLACK_USER_AN_ID=U...
SLACK_USER_BINH_ID=U...
SLACK_USER_CHI_ID=U...
```

Nếu đang demo một mình, dùng chính Member ID của bạn cho cả ba biến. Slack sẽ gửi
cả ba loại thông báo vào cùng một DM; nội dung thông báo vẫn ghi rõ vai trò An,
Bình hoặc Chi. Khi có ba tài khoản thật, chỉ cần thay ba Member ID tương ứng.

Không dùng display name hoặc email thay Member ID. Tên có thể đổi/trùng; Member ID
là định danh ổn định mà worker kiểm tra trước khi gọi Slack.

## 5. Điền `.env`

Mở file `.env` tại thư mục gốc và thay các dòng:

```env
DW_SLACK_APPROVALS_ENABLED=true
DW_APPROVAL_REMINDER_SECONDS=5
DW_PUBLIC_WEB_URL=http://localhost:3000

SLACK_BOT_TOKEN=xoxb-token-that-came-from-slack
SLACK_USER_AN_ID=U_AN
SLACK_USER_BINH_ID=U_BINH
SLACK_USER_CHI_ID=U_CHI
SLACK_USER_MAP_JSON=
```

`SLACK_USER_MAP_JSON` để trống cho ba tài khoản demo. Khi tích hợp OIDC/danh bạ
thật, có thể thêm mapping subject:

```env
SLACK_USER_MAP_JSON={"oidc-subject-123":"U01234567"}
```

Không thêm dấu nháy quanh toàn bộ token. Không chèn khoảng trắng trước/sau dấu `=`.

## 6. Chạy Docker

Từ thư mục gốc:

```powershell
docker compose --env-file .env -f infra/compose/docker-compose.yml --profile full up -d --build
docker compose --env-file .env -f infra/compose/docker-compose.yml --profile full ps -a
```

Profile `full` tự chạy migration `0011` và seed idempotent ba tài khoản demo trước
khi API khởi động.

Các service `migrate`, `seed` và `minio-setup` là one-shot nên trạng thái đúng của
chúng là `Exited (0)`. Các service dài hạn phải là `Up (healthy)`.

Kiểm tra worker đã bật consumer:

```powershell
docker compose --env-file .env -f infra/compose/docker-compose.yml logs worker --tail 100
```

Phải thấy:

```text
Slack approval notification consumer registered
```

Nếu thấy `Slack approval notifications disabled`, kiểm tra
`DW_SLACK_APPROVALS_ENABLED=true` và recreate worker:

```powershell
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d --force-recreate worker
```

## 7. Chạy kịch bản xác nhận

1. Đăng nhập web bằng `an.nguyen`.
2. Tạo case DW01 mới.
3. Trong vài giây:
   - Bình nhận DM `Yêu cầu mới cần phê duyệt`.
   - Trang case hiển thị job `intake.approval_requested = sent`.
4. Không xử lý trong 5 giây:
   - Chi nhận DM `Nhắc việc phê duyệt quá hạn`.
   - Job `intake.approval_escalated = sent`.
5. Bình bấm **Mở hồ sơ DW01**, đăng nhập `binh.tran`.
6. Thử một trong hai nhánh:
   - Điền approval reference và chọn **Xác nhận intake**: An nhận DM đã duyệt.
   - Nhập lý do và chọn **Từ chối và báo An**: An nhận DM kèm lý do.
7. Mở nhật ký Slack trên trang case:
   - `sent`: Slack trả về thành công.
   - `queued`: đang chờ hoặc chờ retry.
   - `cancelled`: reminder bị huỷ vì case đã được xử lý.
   - `failed`: đã hết số lần retry; xem `last_error`.

Để kiểm tra nhánh “không gửi nhắc Chi”, tạo case khác và cho Bình duyệt trong vòng
5 giây. Job escalation phải chuyển thành `cancelled`.

## 8. Xử lý lỗi thường gặp

| Lỗi trong `last_error` | Nguyên nhân thường gặp | Cách xử lý |
| --- | --- | --- |
| `invalid_auth` | Token sai, bị revoke hoặc không phải `xoxb-` | Cài/reinstall app và lấy lại Bot User OAuth Token |
| `missing_scope` | Thiếu `chat:write` hoặc `im:write` | Thêm scope, **Reinstall to Workspace**, restart worker |
| `no Slack member mapping` | Thiếu/sai biến Member ID | Kiểm tra ba biến `SLACK_USER_*_ID` |
| `user_not_found` | Member ID không thuộc workspace đã cài app | Copy lại ID từ đúng workspace |
| timeout/network | Docker không ra được `slack.com` | Kiểm tra proxy, DNS và firewall; worker tự retry |

Sau khi sửa `.env`, recreate worker. Không cần xoá database; job đang `queued` sẽ
được xử lý tiếp.

## 9. Cấu hình khi chuyển khỏi demo

- Đổi `DW_APPROVAL_REMINDER_SECONDS=5` thành SLA thật, ví dụ `1800`.
- Quản lý token bằng Docker Secret/Vault thay vì file `.env`.
- Thay mapping demo bằng bảng directory tenant-scoped hoặc mapping subject OIDC.
- Thiết lập monitoring cho job `failed`, tuổi job `queued` và Slack API latency.
- Quy định business calendar, nhiều cấp escalation và thời hạn theo loại approval.
- Chỉ bổ sung Signing Secret/public HTTPS hoặc Socket Mode nếu sau này muốn bấm
  Approve/Reject trực tiếp trong Slack.
