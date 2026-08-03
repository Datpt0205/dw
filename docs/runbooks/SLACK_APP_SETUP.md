# Slack App Setup — DW01 Chat Front Office (Socket Mode)

Lớp chat cho phép An nhắn Slack («Tôi muốn mua 100 laptop») → Digital Worker
hỏi phần còn thiếu → xác nhận → tạo hồ sơ DW01 → luồng phê duyệt hiện có chạy
tiếp (Bình nhận DM như cũ). Slack **không phải** source of truth và **không
phải** authorization — danh tính map qua cấu hình, quyền vẫn do membership DB
quyết định.

## 1. Dùng lại app Slack hiện có

Không cần tạo app mới — dùng đúng app đang gửi DM phê duyệt (đã có Bot Token
`xoxb-…` trong `.env`). Chỉ cần **bật thêm chiều nhận**:

### 1.1. Bật Socket Mode (không cần public URL)

1. Mở <https://api.slack.com/apps> → chọn app DW → **Settings → Socket Mode**.
2. Bật **Enable Socket Mode**. Slack yêu cầu tạo **App-Level Token**:
    - Name: `dw-socket`
    - Scope: `connections:write`
3. Copy token `xapp-1-…` → dán vào `.env`:

    ```env
    SLACK_APP_TOKEN=xapp-1-...
    DW_CHAT_FRONT_OFFICE_ENABLED=true
    ```

### 1.2. Event Subscriptions

**Features → Event Subscriptions** → bật **Enable Events** (khi Socket Mode đã
bật thì KHÔNG cần Request URL). Trong **Subscribe to bot events** thêm:

| Event         | Mục đích                       |
| ------------- | ------------------------------ |
| `message.im`  | Nhận DM người dùng gửi cho bot |
| `app_mention` | Nhận `@DW …` trong channel     |

Save Changes.

### 1.3. Interactivity (nút bấm)

**Features → Interactivity & Shortcuts** → bật **Interactivity**. Với Socket
Mode không cần Request URL. (Nút «Tạo hồ sơ / Sửa thông tin» dùng đường này.)

### 1.4. OAuth Scopes

**OAuth & Permissions → Bot Token Scopes** — bảo đảm có (thêm nếu thiếu):

| Scope               | Vì sao                                                            |
| ------------------- | ----------------------------------------------------------------- |
| `chat:write`        | Gửi/cập nhật tin nhắn (đã có từ trước)                            |
| `im:history`        | Đọc DM gửi cho bot (message.im)                                   |
| `app_mentions:read` | Đọc tin nhắn @mention                                             |
| `im:write`          | Mở DM (đã dùng cho thông báo phê duyệt)                           |
| `files:read`        | Tải file HSDT do quản lý thả vào DM (bàn tiếp nhận hồ sơ dự thầu) |

Nếu vừa thêm scope → **Reinstall to Workspace** (Install App → Reinstall).
Token `xoxb-` giữ nguyên trừ khi Slack yêu cầu cấp lại — nếu cấp lại thì cập
nhật `SLACK_BOT_TOKEN` trong `.env`.

### 1.5. Cho phép người dùng DM bot

**App Home → Show Tabs → Messages Tab**: tick **Allow users to send Slash
commands and messages from the messages tab** (nếu chưa).

## 2. Map danh tính (đã có sẵn)

Slack member ID → người dùng DW lấy từ chính cấu hình outbound đang dùng:

```env
SLACK_USER_AN_ID=U…    # dev|an.nguyen
SLACK_USER_BINH_ID=U…  # dev|binh.tran
SLACK_USER_CHI_ID=U…   # dev|chi.le
```

Có thể override/bổ sung qua `configs/demo/channel_identities.yaml` (mục
`slack:`) hoặc `SLACK_USER_MAP_JSON`. Người chưa map nhắn bot sẽ nhận hướng
dẫn kèm Slack ID của họ. Mọi command sau đó vẫn qua kiểm tra membership DB
(RLS/scopes) — map sai chỉ dẫn tới từ chối truy cập, không leo quyền.

## 3. Chạy

```powershell
# migration mới (tender.chat_conversations + platform.channel_event_dedupe)
make migrate     # hoặc: uv run alembic -c db/alembic.ini upgrade head

# API bật cờ chat (đọc .env qua compose)
docker compose --profile full up -d --build api
docker logs dw-api 2>&1 | Select-String "slack"   # "slack socket-mode connected"
```

## 4. Demo script

1. **An** (Slack) DM bot: `Tôi muốn mua 100 laptop cho developer`.
2. Bot hỏi gộp phần thiếu (ngân sách, thời hạn, nơi giao, NCC tối thiểu theo
   rule pack…). An trả lời tự nhiên: `2 tỷ, cần trong 45 ngày, giao Hà Nội,
mời FPT, CMC, Viettel`.
3. Bot hiển thị **thẻ xác nhận** (confirm-before-commit) → An bấm **Tạo hồ sơ**.
4. Hồ sơ DW01 được tạo bằng đúng command của web UI; **Bình** nhận DM phê duyệt
   như luồng hiện có; web UI thành back-office xem chi tiết.
5. Nhắn `thôi, huỷ đi` để huỷ phiên thu thập.

## 5. Sự cố thường gặp

| Triệu chứng                                       | Nguyên nhân / xử lý                                                 |
| ------------------------------------------------- | ------------------------------------------------------------------- |
| Log `SLACK_APP_TOKEN missing or not an app token` | Token phải bắt đầu `xapp-` (không phải `xoxb-`)                     |
| Bot không phản hồi DM                             | Chưa subscribe `message.im`, hoặc chưa Reinstall sau khi thêm scope |
| `missing_scope` trong log                         | Thiếu scope ở §1.4 → thêm + Reinstall                               |
| Bot trả lời 2 lần                                 | Không xảy ra: event được dedupe qua `platform.channel_event_dedupe` |
| Người lạ nhắn bot                                 | Nhận hướng dẫn map ID; không truy cập được dữ liệu case             |

## 6. Phạm vi đã phủ (P0-P8 hoàn tất)

- **Toàn bộ vòng đời qua Slack**: intake hội thoại → verify → CP1-CP4 (nút
  duyệt trên card) → phát hành → addendum/CP3 → ghi nhận HSDT → mở thầu/CP4 →
  handoff. Docs (PR, addendum, biên nhận, biên bản mở thầu) tự sinh — không
  upload. Trả lời làm rõ (`waiting_clarification`) cũng qua chat.
- **Review Agent (P5)**: đề xuất + căn cứ trên card CP1/CP2 (deepseek-reasoner).
- **Autonomy (P6)**: `DW_AUTONOMY_PROFILE=autonomous_demo` → CP1 tự duyệt cho
  gói chỉ định thầu rủi ro thấp; mặc định `governed_production` luôn chờ người.
- **App Home (P7)**: tab Home = "Việc của tôi" (cần bot event `app_home_opened`
    - bật Home Tab).
- **Production ingress (P8)**: đặt `SLACK_SIGNING_SECRET` để bật HTTPS
  endpoints `/api/v1/channels/slack/{events,interactions}` (verify chữ ký,
  chặn replay). Socket Mode vẫn là đường local/demo.
- **Web = read-only back office** (`NEXT_PUBLIC_DW01_READONLY`, mặc định bật):
  chỉ theo dõi/tra cứu; build với `=false` để trả lại nút web khi regression.
