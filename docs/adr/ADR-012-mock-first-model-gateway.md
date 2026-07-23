# ADR-012: Mock-first model gateway; cấm mock ở production profile

- **Status**: Accepted
- **Date**: 2026-07-23

## Context

Môi trường phát triển hiện chưa có LLM credential. Blueprint §30 cấm "mock âm
thầm ở production profile" nhưng yêu cầu luồng demo chạy thật, không
NotImplementedError.

## Decision

- `ModelGateway` port với hai adapter: `MockModelAdapter` (deterministic,
  fixture-driven, output luôn validate qua Pydantic schema) và
  `OpenAICompatibleAdapter` (real provider, bật qua `DW_MODEL_PROVIDER` + API key).
- Profile `local`/`test`: mặc định mock; provider thật bật được qua env.
- Profile `production`: mock bị cấm — composition root fail-fast khi
  `DW_MODEL_PROVIDER=mock` hoặc thiếu credential.
- Fixture của mock nằm cạnh eval datasets để demo và eval dùng chung dữ liệu.

## Consequences

- Demo/E2E/CI chạy ổn định không cần secret; đổi sang provider thật là việc
  cấu hình, không phải việc code.
- Kết quả mock phải realistic (schema-valid, có evidence refs) để UI và eval có ý nghĩa.
