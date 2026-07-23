# ADR-014: Outbox polling + Redis Streams cho queue POC; không Kafka/RabbitMQ

- **Status**: Accepted
- **Date**: 2026-07-23

## Context

Side effect phải đi qua transactional outbox (blueprint §7.8). POC cần transport
nhẹ giữa API và worker process; Redis/Valkey không được là source of truth (§4.4).

## Decision

- Nguồn sự thật của event là bảng `platform.outbox_events` trong PostgreSQL
  (ghi cùng transaction với aggregate).
- Worker process poll outbox (FOR UPDATE SKIP LOCKED) để publish/execute side
  effect; idempotency key + processed marker chống trùng.
- Redis Streams chỉ được dùng làm wake-up/queue nhẹ tùy chọn để giảm độ trễ
  polling; mất Redis không mất dữ liệu — hệ thống quay về polling.
- Kafka/RabbitMQ/Temporal chỉ thêm khi có yêu cầu scale/durability thực tế,
  qua adapter mới của cùng port.

## Consequences

- Đơn giản vận hành POC (không thêm broker); vẫn đúng at-least-once + idempotent.
- Throughput giới hạn bởi polling — chấp nhận được cho POC, có đường nâng cấp rõ.
