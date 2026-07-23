# ADR-011: Phase mapping — kế hoạch 7 phase thay cho thứ tự §28 blueprint

- **Status**: Accepted
- **Date**: 2026-07-23

## Context

Blueprint §28 định nghĩa Phase 0–7 (knowledge/memory ở Phase 5, UI ở Phase 6).
Yêu cầu triển khai thực tế dùng cấu trúc 7 phase: Phase 2 gộp agent runtime +
model gateway + memory + knowledge + tool registry; UI được xây dần theo từng
vertical slice; Phase 5 gom evaluation/observability/audit/release.

## Decision

Dùng phase plan trong `docs/implementation/IMPLEMENTATION_PLAN.md`:

| Plan phase                               | Blueprint §28 tương ứng |
| ---------------------------------------- | ----------------------- |
| 0 Bootstrap + Docker                     | 28.1                    |
| 1 Kernel/tenancy/identity/authz          | 28.2                    |
| 2 Runtime/gateway/memory/knowledge/tools | 28.3 + 28.6 (nền tảng)  |
| 3 Meeting-to-action slice (kèm UI slice) | 28.4 + một phần 28.7    |
| 4 Tender slice (kèm UI slice)            | 28.5 + một phần 28.7    |
| 5 Eval/observability/audit/release       | 28.7 + 28.8 (một phần)  |
| 6 Hardening + acceptance                 | 28.8                    |

Không deliverable nào của §28 bị bỏ; chỉ đổi thứ tự để ưu tiên thin vertical
slice (§34) và để knowledge/memory sẵn sàng trước khi slice cần evidence.

## Consequences

- Acceptance criteria của từng phase §28 được giữ nguyên và map vào plan phase.
- Mọi thay đổi thứ tự tiếp theo phải cập nhật ADR này.
