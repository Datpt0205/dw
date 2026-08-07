# ADR-020 — Visible thinking lấy từ reasoning của model (OpenAI Responses API)

- **Trạng thái:** Accepted (2026-08-04)
- **Bối cảnh trước đó:** plan §7.5 và ADR-012/017 — dòng "Suy nghĩ" hiển thị
  trên kênh chat được DỰNG BẰNG CODE (`_build_thinking`: slot diff đã
  validate + đối chiếu rule pack), chủ đích "auditable, no self-report".

## Quyết định

1. Dòng "Suy nghĩ" hiển thị ưu tiên **reasoning trace do model tự sinh**:
    - OpenAI: **reasoning summary** từ `/v1/responses`
      (`reasoning: {summary: "auto"}`) — bản tóm tắt chính thức của chuỗi
      reasoning nội bộ GPT-5; API không bao giờ trả raw chain-of-thought.
    - DeepSeek-style reasoner: `reasoning_content` (đường cũ, vẫn hoạt động).
2. Thêm adapter mới `OpenAIResponsesAdapter` (provider id `openai_responses`)
   cạnh `OpenAICompatibleAdapter` — cùng port `ModelProviderAdapter`, cùng
   credentials, chỉ khác dialect. Profile chọn qua `provider:` trong
   `configs/models/*.yaml`; profile `openai` dùng nó cho cả 3 route.
3. **Fallback bắt buộc:** provider không trả reasoning (mock,
   chat/completions) → dùng lại `_build_thinking`. Kênh chat không bao giờ
   mất dòng suy nghĩ.
4. **Guard lines không thương lượng:** các dòng hệ thống (money guard, v.v.)
   luôn được NỐI THÊM vào thinking hiển thị, kể cả khi thinking là của model —
   phần kiểm chứng deterministic không phụ thuộc lời kể của model.

## Mở rộng (cùng ngày) — nhóm 2: reply và văn bản do LLM soạn

5. **Reply lifecycle 2-pass** (`_compose_reply`): các câu trả lời Slack cho
   addendum/ghi nhận HSDT/mở thầu/huỷ/trạng thái... được LLM soạn từ FACTS
   hệ thống cung cấp SAU khi hành động đã thực hiện/xác minh xong (prompt
   `conversation.compose_reply`). Presentation-only: mọi lỗi model → dùng
   lại câu template cứng. Mock provider không có fixture cho các prompt
   presentation — cố ý, để demo mock luôn dùng câu đúng ngữ cảnh.
6. **Thân addendum do LLM soạn** (`conversation.draft_addendum`): phần
   "Nội dung sửa đổi/Đánh giá ảnh hưởng/Hạng mục bị ảnh hưởng" do model
   viết; header metadata + trích NGUYÊN VĂN tin nhắn Slack luôn do code dựng
   (dấu vết audit). Model lỗi → thân văn bản dùng nguyên văn phát biểu thô.
7. GIỮ deterministic (không chuyển): chấm điểm trọng số, gate/rule pack,
   money guard, biên nhận HSDT, biên bản mở thầu, sổ tiếp nhận, confirm card,
   text UI thuần (case picker, đổi ngữ cảnh hồ sơ).

## Hệ quả / đánh đổi

- Chấp nhận rủi ro "model kể không khớp việc hệ thống làm" (lý do của thiết
  kế cũ) để đổi lấy suy nghĩ thật, giàu ngữ cảnh hơn. Giảm thiểu bằng (3)+(4)
  và bằng việc reasoning summary là bản tóm tắt do OpenAI sinh từ reasoning
  thật, không phải văn model tự bịa sau khi trả lời.
- Test `test_thinking_is_deterministic_trace_not_model_narration` (chính sách
  cũ) được thay bằng cặp test: model-thinking-được-ưu-tiên và
  fallback-khi-trống.
- Chi phí: reasoning summary tính token output; mức tăng nhỏ so với đáp án
  JSON (đã tính dư trong dự toán ngân sách demo).
