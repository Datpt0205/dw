# ADR-003: Clean/Hexagonal dependency rule + enforcement

- **Status**: Accepted
- **Date**: 2026-07-23

## Context

Domain logic phải sống lâu hơn framework và provider. Blueprint §7 quy định
dependency luôn hướng vào trong.

## Decision

Mỗi bounded context có 4 lớp: `domain`, `application`, `adapters`, `presentation`
(+ `workflows` cho graph). Quy tắc:

```text
presentation ──> application ──> domain
adapters ──────> application ports
composition root (apps/api, apps/worker) ──> tất cả để wiring
```

- Domain: stdlib (+ dataclass); cấm FastAPI/SQLAlchemy/LangGraph/Qdrant/provider SDK.
- Pydantic dùng cho boundary DTO (application/contracts); value object domain dùng dataclass.
- Constructor dependency injection; cấm service locator và global mutable singleton.
- Enforcement 2 tầng: `import-linter` (pyproject `[tool.importlinter]`) và
  `scripts/verify_architecture.py` (declared-dependency check), chạy trong
  `make test-architecture` và CI.

## Consequences

- Thêm một adapter mới không đụng domain/application.
- Test dùng fake ports, không cần database/LLM cho unit tests.
- Vi phạm boundary làm CI đỏ ngay, không cần review thủ công.
