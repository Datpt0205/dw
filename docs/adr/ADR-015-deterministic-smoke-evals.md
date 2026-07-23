# ADR-015 — Smoke evals chấm các chốt chặn deterministic, không chấm model

Trạng thái: Accepted (2026-07-23)

## Bối cảnh

Blueprint §22 yêu cầu eval smoke chạy trong CI cho mọi commit, gồm bắt buộc
các case bảo mật (prompt injection, cross-tenant attack, missing evidence).
POC chạy mock model deterministic; CI không có key provider thật.

## Quyết định

`make eval-smoke` chấm **các safety gate deterministic** — những lớp phải giữ
vững _kể cả khi model sai_: scoring engine (golden numbers, fail-closed),
evidence locator (quote bịa không thành bằng chứng), prompt containment
(injection bị giam trong block untrusted), trusted tenant filter, memory
provenance policy, ambiguous-identity refusal, tool approval policy. Grader
gọi thẳng component production, không mock lại logic.

Eval chất lượng model (đúng/đủ nội dung trích xuất) chạy ở
`eval-regression.yml` khi có key provider — cùng dataset schema, thêm grader
model-backed.

## Hệ quả

- CI chặn được regression an ninh mà không cần LLM và không flaky.
- Dataset versioned (`evals/datasets/*@x.y.z.json`), thiếu security category
  → runner fail; checksum dataset nằm trong release manifest.
- Đánh đổi: smoke không đo chất lượng model — chấp nhận, vì kiến trúc
  "LLM đề xuất, code quyết định" đặt an toàn ở phần code được chấm.
