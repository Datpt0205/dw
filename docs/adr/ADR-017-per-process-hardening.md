# ADR-017 — Hardening POC: rate limit per-process, circuit breaker, SSRF guard

Trạng thái: Accepted (2026-07-23)

## Bối cảnh

Blueprint yêu cầu idempotency/timeout/retry/circuit-breaker boundaries và
kiểm soát outbound. POC chạy một instance API (modular monolith).

## Quyết định

1. **Rate limit**: middleware fixed-window 60s per-caller (hash bearer token,
   fallback IP), mặc định 240 req/phút, 429 + Retry-After, health exempt.
   Bộ đếm in-process — đúng cho single-instance; multi-instance chuyển bộ đếm
   sang Redis _sau cùng middleware seam_ (Redis vẫn không phải source of
   truth: mất counter chỉ nới lỏng limit tạm thời).
2. **Circuit breaker**: `dw_kernel.resilience.CircuitBreaker` thuần stdlib,
   clock-injected (test deterministic), 5 lỗi liên tiếp → OPEN 30s →
   HALF_OPEN 1 call thử. Gắn vào `OpenAICompatibleAdapter`; chỉ lỗi hạ tầng
   (timeout/HTTP) mới đếm, lỗi nghiệp vụ không trip.
3. **SSRF guard**: `dw_kernel.net_guard.ensure_allowed_outbound_url` — chỉ
   http(s), cấm credential nhúng, resolve DNS và cấm private/loopback/
   link-local/reserved. `allow_private` suy từ profile (local/test được gọi
   Ollama/vLLM localhost; production không bao giờ), cộng allowlist tường minh
   `DW_API_OUTBOUND_ALLOWED_HOSTS`. Composition root gọi guard khi wire
   provider adapter.

## Hệ quả

- Cả ba primitive nằm ở kernel/middleware, test được bằng unit test không
  cần hạ tầng.
- Đánh đổi đã ghi trong threat model: rate limit chưa phân tán; guard
  resolve-time không chặn DNS-rebinding sau resolve (chấp nhận ở POC, ghi
  nhận cho production).
