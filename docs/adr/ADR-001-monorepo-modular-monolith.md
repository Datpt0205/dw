# ADR-001: Một monorepo, modular monolith + async worker process

- **Status**: Accepted
- **Date**: 2026-07-23

## Context

Nền tảng phục vụ hai Digital Worker với nhiều capability nền tảng dùng chung
(tenancy, model gateway, approval, audit, knowledge, memory). POC cần dựng nhanh
nhưng phải tiến hóa được thành sản phẩm enterprise mà không viết lại.

## Decision

- Một monorepo duy nhất: uv workspace (Python) + pnpm workspace (TypeScript).
- Modular monolith: một API process (FastAPI), một async worker process, một web app.
- Module hóa bằng packages độc lập (`packages/python/*`), mỗi package có
  pyproject và dependency khai báo tường minh; không package nào "ăn ké"
  dependency của package khác (enforce bằng `scripts/verify_architecture.py`).

## Consequences

- Tách microservice sau này = thay adapter/transport, không đổi domain/application
  (điều kiện tách: scale độc lập, compliance, team ownership — blueprint §2.2).
- Một lockfile Python (`uv.lock`) + một lockfile Node (`pnpm-lock.yaml`).
- CI chạy trên toàn workspace; boundary được bảo vệ bằng import-linter.
