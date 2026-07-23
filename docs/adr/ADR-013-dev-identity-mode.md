# ADR-013: Dev identity mode + Keycloak OIDC sau cùng một TokenVerifierPort

- **Status**: Accepted
- **Date**: 2026-07-23

## Context

Blueprint yêu cầu "login mock hoặc OIDC-ready" (§3.1) và Keycloak cho local
compose (§20.1). Test/dev không nên phụ thuộc một Keycloak đang chạy.

## Decision

- `TokenVerifierPort` (dw_platform.application.ports) là contract duy nhất để
  xác minh token.
- `KeycloakOidcAdapter`: verify issuer/audience/signature/expiry qua JWKS —
  dùng cho compose profile full và production.
- `DevIdentityAdapter`: JWT ký bằng local secret, chỉ được wire khi profile là
  `local`/`test`; production fail-fast nếu bật.
- `AccessContext` luôn được build từ verified claims + membership trong DB;
  không tin `tenant_id` từ client (blueprint §15.2).

## Consequences

- Integration/E2E test chạy không cần Keycloak container.
- Cả hai adapter đi qua cùng flow build AccessContext → không có đường tắt auth nào khác.
