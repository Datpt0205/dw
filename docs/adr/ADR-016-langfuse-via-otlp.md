# ADR-016 — Observability qua TelemetryPort; Langfuse là một OTLP endpoint

Trạng thái: Accepted (2026-07-23)

## Bối cảnh

Blueprint §21 yêu cầu OTel instrumentation và Langfuse optional sau cấu hình.
Langfuse SDK v3 kéo theo cây dependency lớn và chính nó cũng bọc OTel.

## Quyết định

1. Runtime code phát telemetry qua `TelemetryPort` (span + counter) —
   constructor-injected, `NullTelemetry` mặc định, `RecordingTelemetry` cho
   test. Runtime không import trực tiếp OTel API ngoài package
   `dw_observability`.
2. `OtelTelemetry` là adapter duy nhất; attribute đi qua `safe_attributes()`
   (redaction + coercion) trước khi rời process.
3. Langfuse KHÔNG có SDK riêng: Langfuse v3 nhận OTLP traces tại
   `/api/public/otel/v1/traces` với Basic auth từ project keys —
   `langfuse_otlp_config()` chỉ dựng (endpoint, headers) cho exporter chuẩn.
   Bật bằng `LANGFUSE_ENABLED=true` + host/keys; thiếu key → fail-fast.

## Hệ quả

- Không thêm dependency ngoài `opentelemetry-{api,sdk,exporter-otlp-proto-http}`.
- Đổi backend (Jaeger/Tempo/Langfuse) là đổi endpoint, không đổi code.
- Đánh đổi: không dùng được tính năng SDK riêng của Langfuse (score API,
  prompt management) — khi cần sẽ là adapter mới sau cùng port.
