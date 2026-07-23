# Phase 7 — Channel intake (Telegram) + real dispatch (Slack) + meeting analysis

- **Status**: 7A/7B/7C CODE DONE (2026-07-23) — chờ token thật + Docker để verify E2E.
- **Đổi kênh**: Zalo OA → **Telegram bot** (BotFather tạo token tức thì, long-polling
  getUpdates nên KHÔNG cần webhook/tunnel; Zalo OA cần duyệt nhiều ngày).
- **Quyết định nền**: giữ core hiện tại (LangGraph sau `WorkflowRunnerPort`); KHÔNG swap Langflow.
  Langflow chỉ cân nhắc sau này như một runner adapter song song cho việc thử nghiệm agent
  (xem phân tích trong ADR-018 khi tạo).

## Mục tiêu end-to-end

> Quăng transcript vào bot Telegram (hoặc khung chat trên web) → BE chạy luồng
> work_ops: tóm tắt, phân tích (điểm tốt / chưa tốt / khuyến nghị), action
> items có người phụ trách → approval (human-in-command, giữ nguyên A2) →
> dispatch task qua Slack thật → bot trả về tóm tắt + link phê duyệt.

## Phase 7A — Slack connector thật (thay Mock, config-switch)

### Scope

- `dw_connectors/adapters/slack_task_connector.py` implements `TaskConnectorPort`:
    - `chat.postMessage` tới channel/DM người nhận (map từ organization directory —
      thêm cột `slack_user_id` vào seed memberships hoặc bảng mapping riêng).
    - Block Kit message: title, mô tả, hạn, nút link về task.
    - Idempotency: dùng key hiện có của ToolExecutor; connector trả `external_ref`
      = `channel:ts` của message.
    - Retry/timeout theo ToolDefinition; circuit breaker dùng `dw_kernel.resilience`.
    - SSRF guard: chỉ gọi `https://slack.com/api/*` (allowlist).
- Settings: `SLACK_BOT_TOKEN`, `SLACK_DEFAULT_CHANNEL`, `DW_TASK_CONNECTOR=mock|slack`
  (production cấm mock — giống ADR-012 với model).
- Bootstrap: chọn connector theo config; tool definition giữ nguyên
  `task.create_external` (approval_policy=always) — chỉ đổi adapter.

### Tests

- Unit: adapter với httpx mock transport (post đúng payload, parse lỗi Slack `ok:false`).
- Integration (tuỳ chọn, cần token thật trong env local — skip trên CI).
- E2E hiện có vẫn chạy với mock (CI không cần token).

### Chuẩn bị từ phía người dùng

- Tạo Slack app tại api.slack.com → Bot Token Scopes: `chat:write`, `users:read`,
  (`chat:write.public` nếu post vào channel chưa invite) → cài vào workspace →
  lấy `xoxb-...` token, điền `.env`.

## Phase 7B — Graph work_ops v1.1.0: node phân tích cuộc họp

### Scope

- Prompt bundle mới `configs/prompts/work_ops/analyze_meeting@1.0.0.yaml`
  (system chống injection như các prompt hiện có): input transcript đã chuẩn hoá,
  output schema: `went_well[]`, `needs_improvement[]`, `recommendations[]`,
  mỗi mục kèm `evidence_quote`.
- DTO Pydantic `MeetingAnalysis` + validate qua model gateway (như mọi LLM output).
- Node `analyze_meeting` chèn sau summarize; lưu vào `meetings.analysis` (JSONB —
  migration 0005 thêm cột, RLS thừa hưởng bảng cũ).
- Version bump: graph_version 1.1.0, worker_version 1.1.0, prompt_bundle 1.1.0
  trong `configs/workers/work_ops.yaml`; release manifest đổi theo (đúng luật §23).
- Mock fixture mới cho eval/mock model; eval case normal cho analysis
  (grounding: quote phải locate được trong transcript — tái dùng evidence locator? —
  transcript grounding dùng parser offset, thêm grader nếu gọn).
- UI meeting detail: card "Phân tích cuộc họp" (3 cột tốt/chưa tốt/khuyến nghị).

### Tests

- Unit schema + node routing; integration E2E work_ops assert analysis có mặt
  và quote grounded; contract regen OpenAPI.

## Phase 7C — Telegram bot intake (DONE)

- `apps/api/src/dw_api/channels/telegram.py`: long-polling `getUpdates`
  (không cần webhook/tunnel); transcript trong chat → tạo meeting → chạy graph
  → trả về điểm chất lượng họp + điểm tốt/chưa tốt + link phê duyệt.
- Identity: Telegram user id → subject qua `configs/demo/channel_identities.yaml`;
  membership vẫn verify trong DB — chat không bao giờ là authorization.
- Khung chat native trên web (`apps/web/components/assistant-chat.tsx`) dùng
  cùng luồng, không phụ thuộc nền tảng ngoài.
- Env: `TELEGRAM_BOT_TOKEN` (BotFather).

## Phase 7D (sau, tuỳ chọn)

- Phê duyệt trực tiếp từ Slack (interactive button → decide approval).
- Teams adapter (Graph API) sau cùng port với Slack.
- Langflow studio container (profile riêng) nếu cần canvas thử nghiệm — ADR riêng.

## Thứ tự làm & lý do

7A trước (không phụ thuộc bên ngoài ngoài 1 token, thay Mock là thấy giá trị ngay)
→ 7B (thuần nội bộ, mock model chạy được, demo "phân tích họp" ngay trên web)
→ 7C (cần tài khoản Zalo OA + tunnel, nhiều mảnh bên ngoài nhất)
→ 7D.

## Nguyên tắc giữ nguyên

- Mọi side effect qua ToolExecutor (idempotency + audit + approval).
- Channel chỉ là intake/notify — không bao giờ là authorization
  (Zalo message không thể tự approve).
- Mọi artifact mới đều versioned; secrets chỉ trong env.
