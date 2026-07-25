# Kịch bản demo — Digital Worker (DW01 đấu thầu + RAG)

Demo end-to-end: đăng nhập OIDC role-aware → upload tài liệu vào RAG (Docling/OCR,
scope tenant/global) → chạy Digital Worker chuẩn bị gói thầu DW01 với 2 chốt phê
duyệt (CP1/CP2) và trích dẫn bằng chứng từ RAG → cô lập đa tenant.

## 0. Chuẩn bị (một lần)

```bash
# Bật full stack (đã build sẵn image api/web/worker)
docker compose -f infra/compose/docker-compose.yml --env-file .env --profile full up -d --wait
```

- Web: <http://localhost:3000> · API: <http://localhost:8000> · Keycloak: <http://localhost:8686>
- Keycloak chạy ở **8686** (đã chủ động dời khỏi 8080 để tránh đụng app khác trên máy).
  Nếu cổng bị chiếm sau khi Docker restart: giải phóng rồi
  `docker compose ... up -d --force-recreate keycloak`.
- Tài khoản (mật khẩu `demo-password`, đều thuộc **tenant Alpha**):

  | Tài khoản    | Vai trò              | Làm được gì trong demo                         |
  | ------------ | -------------------- | ---------------------------------------------- |
  | `an.nguyen`  | member               | tạo/upload, chạy DW01 — KHÔNG phê duyệt         |
  | `binh.tran`  | approver (+member)   | phê duyệt CP1/CP2                              |
  | `chi.le`     | platform_admin (+m)  | thấy Admin, upload **luật global** cho mọi tenant |

## 1. Đăng nhập OIDC + UI theo vai trò (2 phút)

1. Mở <http://localhost:3000> → chuyển hướng sang Keycloak. Đăng nhập `an.nguyen`.
2. Chỉ ra **sidebar chỉ hiện chức năng mà role được phép**: member thấy Đấu thầu,
   Knowledge, Inbox… nhưng **không thấy nút phê duyệt/Admin**.
3. Đăng xuất → đăng nhập `binh.tran` (approver): xuất hiện thêm quyền **Phê duyệt**.
4. Đăng nhập `chi.le` (platform_admin): xuất hiện **Admin** + được upload scope global.

> Điểm nhấn: phân quyền do backend cưỡng chế (scope/role); UI chỉ ẩn nút cho gọn —
> gọi thẳng API mà thiếu quyền vẫn 403.

## 2. Đăng ký tài khoản mới (1 phút)

1. Ở màn login Keycloak → **Register** → tạo tài khoản mới.
2. Đăng nhập lần đầu → hệ thống **tự tạo user thật trong Postgres**, gắn vào
   **tenant Alpha, role `member`** (auto-provisioning qua `external_identities`).
3. Cho xem: tài khoản mới thấy đúng giao diện member (không có phê duyệt/Admin).

## 3. Knowledge / RAG — upload tài liệu (4 phút)

Vào **Knowledge** (sidebar).

1. **Luật global** (đăng nhập `chi.le`): upload 1 file luật (PDF/DOCX/ảnh scan),
   Loại = *Pháp lý*, Phạm vi = **Global**. → trạng thái *đang xử lý* → **hoàn tất, N chunk**.
   - Điểm nhấn: worker **Docling** parse đa định dạng + **OCR** cho bản scan, bảng →
     Markdown; nhúng bằng **BGE-M3 (self-host)**, index vào Qdrant kèm filter tenant.
2. **Quy chế nội bộ** (đăng nhập `an.nguyen`): upload 1 file quy chế, Loại =
   *Quy chế*, Phạm vi = **Tenant** (riêng tổ chức).
3. Chỉ ra bảng tài liệu: **badge scope** (global = hổ phách, tenant = xám), số chunk,
   phiên bản, nút **Xoá mềm** (giữ vết, có thể phục hồi).

> Global = luật dùng chung mọi tenant đọc được; Tenant = chỉ tổ chức của bạn thấy.
> Chỉ platform_admin mới đăng được tài liệu global.

## 4. DW01 — Digital Worker chuẩn bị gói thầu (6 phút)

Vào **Đấu thầu → DW01** (`/procurement/dw01`).

1. **Tạo hồ sơ mẫu** (nút trên trang) → sinh 1 case từ PR đã duyệt (fixture laptop).
2. Mở case → **Chạy** để Digital Worker chạy graph:
   - Bóc yêu cầu → kiểm tra đầy đủ → **đề xuất phương án mua sắm** (chọn hình thức theo
     rule pack + **trích dẫn luật/quy chế từ RAG** — chỉ mục `legal_basis`, `policy_basis`).
   - Dừng ở **CP1 — Duyệt phương án** (interrupt bền vững, run được checkpoint).
3. Đăng nhập `binh.tran` (approver) → **Phê duyệt CP1**. Run **tự tiếp tục**:
   - Dựng **hồ sơ mời thầu (HSMT)**, **tiêu chí đánh giá**, **shortlist NCC** — các
     artifact kèm **references** trích từ RAG.
   - Dừng ở **CP2 — Duyệt bộ hồ sơ**.
4. `binh.tran` **Phê duyệt CP2** → **khoá bản chính thức** + **export gói đánh giá**
   (lưu MinIO), trạng thái case = *hoàn tất*.

> Điểm nhấn: một agentic workflow/bounded context; state có kiểu + versioned; 2 chốt
> human-in-command; mọi artifact truy vết được về bằng chứng (evidence/citations).

## 5. (Tuỳ chọn) Cô lập đa tenant (2 phút)

- Chế độ dev (`DW_API_AUTH_MODE=dev`, trang `/dev-login`) có sẵn user tenant Beta
  (`bao.pham`, `dung.vo`).
- Đăng nhập tenant Beta → vào Knowledge: **đọc được luật global** của Alpha, nhưng
  **không thấy quy chế nội bộ (tenant)** của Alpha → chứng minh RLS + Qdrant filter.

## Điểm chốt khi demo

- **Human-in-command**: 2 chốt phê duyệt CP1/CP2 pause/resume durable.
- **RAG doanh nghiệp**: Docling+OCR đa định dạng, chunk theo cấu trúc, BGE-M3 self-host
  + rerank, scope global/tenant, xoá mềm + versioning.
- **Bảo mật đa tenant**: RLS Postgres + filter Qdrant; luật global chia sẻ, dữ liệu
  tenant cô lập; upload global chỉ platform_admin.
- **Truy vết**: mọi output DW01 gắn evidence/citations; export gói đánh giá.
