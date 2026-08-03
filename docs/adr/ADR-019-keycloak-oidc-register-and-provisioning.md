# ADR-019: Keycloak OIDC là chế độ mặc định + đăng ký + provisioning lần đầu

- **Status**: Accepted
- **Date**: 2026-07-24
- **Bổ sung cho**: [[ADR-013]] (dev identity mode)

## Context

DW01 yêu cầu login/logout thật bằng Keycloak (Authorization Code + PKCE), có
đăng ký tài khoản, và account mới phải được lưu vào database thật với quyền
nghiệp vụ rõ ràng. Trước đó hệ thống mặc định chạy `auth_mode=dev` (persona
picker + token HS256 trong localStorage) và chỉ tạo tài khoản qua seed script.

Hai ràng buộc kiến trúc:

1. Keycloak quản lý danh tính; Digital Worker quản lý quyền nghiệp vụ
   (role/scope) trong DB. Một Keycloak user mới không có membership → bị chặn.
2. Token `sub` của Keycloak khác `users.subject` của seed (`dev|...`), nên cần
   một lớp ánh xạ.

## Decision

- **OIDC là mặc định** (`DW_API_AUTH_MODE=oidc`, `NEXT_PUBLIC_AUTH_MODE=oidc`).
  Frontend dùng `keycloak-js` với Authorization Code + PKCE S256; access/refresh
  token chỉ nằm trong bộ nhớ (không localStorage). Dev mode vẫn giữ làm fallback
  cho host `make dev` và cho test.
- **Đăng ký**: bật `registrationAllowed` trong realm; nút "Đăng ký" gọi
  `keycloak.register()`.
- **`platform.external_identities`** (issuer, subject) → platform user. Đây là
  identity plane (như `users`): không tenant-scoped, không RLS. Membership lookup
  resolve user qua external identity hoặc `users.subject`.
- **Provisioning lần đầu** (`/api/v1/auth/bootstrap`): một danh tính đã verify
  nhưng chưa từng thấy sẽ được tạo `users` + `external_identities` và thêm vào
  **tenant demo mặc định** với vai `member`. User đã tồn tại/seed không bị
  provision lại (giữ nguyên role). `bootstrap` trả về danh sách workspace +
  role + scope để frontend chọn workspace và gate UI.
- **Tách JWKS khỏi issuer**: trong Docker, token `iss` là URL browser-facing
  (`http://localhost:8686/...`) nhưng API fetch JWKS qua service name nội bộ
  (`http://keycloak:8080/...`) — `KeycloakTokenVerifier` nhận `jwks_url` riêng.
- **UI theo quyền chỉ để rõ ràng**: nav/nút được ẩn/khoá theo scope
  (platform_admin bỏ qua như backend), nhưng backend vẫn là nơi enforce duy nhất.

## Consequences

- Người dùng tự đăng ký được và tài khoản lưu vĩnh viễn trong Postgres, tự động
  có quyền qua đúng cơ chế scope hiện có.
- Demo user Keycloak (an.nguyen/binh.tran/chi.le) có id cố định trong realm và
  được seed external identity → giữ đúng role member/approver/admin khi login OIDC.
- Quản lý role (nâng/hạ) qua UI chưa làm — hiện chỉnh qua seed/DB; là bước kế tiếp.
- Production vẫn fail-fast nếu dùng dev mode ([[ADR-013]]).
