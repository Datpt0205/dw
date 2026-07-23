# ADR-002: Hai bounded context độc lập, không super-agent

- **Status**: Accepted
- **Date**: 2026-07-23

## Context

Tender và Work Operations có ngôn ngữ nghiệp vụ, dữ liệu, quyền hạn và KPI khác
nhau. Một "siêu-agent" nắm mọi dữ liệu và công cụ là rủi ro bảo mật và không
maintain được.

## Decision

- `dw_tender` và `dw_work_ops` là hai bounded context DDD độc lập tuyệt đối;
  không import internals của nhau (enforce: import-linter contract "independence").
- Mỗi context có một agentic workflow riêng (TenderAgent, WorkOpsAgent) với tool
  allowlist, policy và version riêng.
- Giao tiếp chỉ qua public application contract, versioned integration event,
  hoặc shared kernel (`dw_kernel`) — kernel chỉ chứa primitives phổ quát, không
  business logic.
- Multi-agent chỉ được thêm khi có role thật sự độc lập (goal/memory/tool/quyền/KPI riêng).

## Consequences

- Code dùng chung phải được đẩy xuống platform packages (`dw_platform`,
  `dw_agent_runtime`, ...) qua contract công khai, không copy chéo context.
- Model của context này không bao giờ thấy dữ liệu thô của context kia.
