# Runbook DW01 upload-only — Docker demo có kiểm soát

## Mục tiêu và giới hạn trung thực

Luồng này chạy thật trên PostgreSQL, MinIO, Keycloak, API, worker và web. Do
chưa có ERP/DMS/procurement portal, mọi dữ liệu bên ngoài được người dùng tải
lên và được ghi rõ `source_mode=manual_upload` hoặc
`manual_evidence_upload`. Hệ thống không tuyên bố đã gửi email, đồng bộ ERP hay
xác minh supplier master.

Phạm vi:

```text
upload PR → xác minh intake → làm rõ → CP1 → CP2
→ ghi nhận phát hành → (tuỳ chọn addendum CP3)
→ tiếp nhận hồ sơ dự thầu → CP4 → evaluation handoff
```

## Tài khoản

Mật khẩu chung: `demo-password`.

| Tài khoản   | Vai trò trong kịch bản                                                            | Không được làm                                           |
| ----------- | --------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `an.nguyen` | Người lập: upload, trả lời làm rõ, chạy DW01, ghi nhận phát hành và hồ sơ dự thầu | Xác minh intake; duyệt CP1/CP2/CP3/CP4 của case mình tạo |
| `binh.tran` | Người kiểm soát/phê duyệt: xác minh intake, CP1, CP2, CP3, CP4                    | Backend vẫn áp scope và separation of duties             |
| `chi.le`    | Quản trị/quan sát audit, xử lý cấu hình nền tảng                                  | Không dùng thay approver trong kịch bản chuẩn            |

Mỗi lần đổi tài khoản: đăng xuất ở góc dưới sidebar, quay lại màn login và đăng
nhập tài khoản tiếp theo. Không dùng chung tab đang giữ token cũ.

## File mô phỏng

Các file nằm tại `apps/web/public/templates/dw01/` và có thể tải trực tiếp:

1. `/templates/dw01/01-approved-pr.md`
2. `/templates/dw01/02-publication-receipt.md`
3. `/templates/dw01/03-bid-thiet-bi-viet.md`
4. `/templates/dw01/04-bid-minh-long.md`
5. `/templates/dw01/05-bid-opening-minutes.md`
6. `/templates/dw01/06-addendum-optional.md`

Đây là fixture được gắn nhãn mô phỏng; runtime không tự inject các file này.

## Chuẩn bị Docker

Nếu bật thông báo/phê duyệt qua Slack, hoàn thành
[runbook cấu hình Slack](./dw01-slack-approvals.md) trước khi khởi động stack.

```bash
docker compose -f infra/compose/docker-compose.yml --env-file .env \
  --profile full up -d --build
docker compose -f infra/compose/docker-compose.yml --env-file .env \
  --profile full ps -a
```

Kiểm tra `api`, `web`, `worker`, `postgres`, `minio`, `qdrant`, `valkey`,
`keycloak` healthy; các one-shot `migrate`, `seed`, `minio-setup` exit `0`.

## Kịch bản chính

### 1. Người lập tạo case

Đăng nhập `an.nguyen`, mở `/procurement/dw01`.

- Upload `01-approved-pr.md`.
- Nhập `PR-2026-0042`, giá trị `2500000000`, deadline `45 ngày`.
- Nhập ba supplier ứng viên, mỗi dòng một tên.
- Tạo case.

Kỳ vọng: case là `draft / Chờ xác minh intake`; MinIO có file nguyên bản;
PostgreSQL lưu filename, MIME, size và SHA-256.

### 2. Người kiểm soát xác minh intake

Đăng xuất, đăng nhập `binh.tran`, mở lại case.

- Nhập `APPROVAL-PR-2026-0042`.
- Đọc hash/source disclosure.
- Bấm `Xác nhận intake`.

Kỳ vọng: case `intake_ready`; artifact `intake_verification` có người xác minh,
thời gian, approval reference và document hash. Người tạo tự xác minh bị 409.

### 3. Worker dừng vì thiếu làm rõ

Đăng nhập lại `an.nguyen`, bấm `Chạy DW01`.

Kỳ vọng: worker tạo demand/completeness artifacts nhưng không tạo approval CP1;
case `waiting_clarification`. Bốn mục `CHƯA RÕ` xuất hiện.

Điền:

- Bảo hành: `Tối thiểu 24 tháng, hỗ trợ tại chỗ`.
- Hệ điều hành: `Windows 11 Pro bản quyền`.
- Địa điểm: `Kho Công ty Alpha, Hà Nội`.
- Thanh toán: `Trong 30 ngày sau nghiệm thu và hóa đơn hợp lệ`.

Nguồn xác nhận: `Email owner nghiệp vụ ngày 25/07/2026`. Lưu và chạy lại.

### 4. CP1

Kỳ vọng: run dừng `waiting_approval`; approval inbox có decision brief, gate
deterministic, giá trị, hình thức và link về evidence.

Đổi sang `binh.tran`, mở `/approvals`, nhập nhận xét bắt buộc:

`Đã kiểm tra PR, phản hồi làm rõ, số supplier và rule pack demo-v1. Đồng ý CP1.`

Phê duyệt. Worker tự tiếp tục và dừng tại CP2.

### 5. CP2

Ở approval inbox, mở lại case và kiểm tra:

- solicitation package;
- criteria có nguồn `rule_pack`;
- shortlist ghi `pending_verification`, không giả là supplier đã đủ điều kiện;
- risk check ghi rõ chưa có nguồn kiểm tra conflict;
- grounding status/citation.

Nhập nhận xét và duyệt CP2. Kỳ vọng official manifest/package được lưu MinIO,
case `package_official`.

### 6. Ghi nhận phát hành

Đổi sang `an.nguyen`, tải `02-publication-receipt.md`.

- Kênh: `Email công vụ`.
- Người nhận: ba supplier ứng viên.
- Thời điểm phát hành.
- External reference: `RFQ-2026-0042-ISSUE-01`.

Kỳ vọng case `published`, có publication record và receipt hash.

### 7. Nhánh CP3 tuỳ chọn

Trước khi nhận hồ sơ dự thầu, upload `06-addendum-optional.md`, nhập change và
impact summary. Case chuyển `cp3_pending`.

Đổi sang `binh.tran`, nhập reference `CP3-2026-0042`, duyệt hoặc từ chối. Case
quay lại `published`; quyết định và hash addendum được giữ lại.

### 8. Nhận hồ sơ dự thầu

Đổi sang `an.nguyen`. Upload lần lượt file `03` và `04`, nhập supplier,
timestamp, `on_time`. Kỳ vọng mỗi bản gốc có object riêng, hash riêng và
submission register tăng version; retry không được ghi đè file cũ.

### 9. CP4 và bàn giao DW02

Đổi sang `binh.tran`, upload `05-bid-opening-minutes.md`.

- Nhập thời điểm mở.
- Witness: `Trần Thị Bình`, `Nguyễn Văn An`.
- Reference: `CP4-2026-0042`.

Xác nhận CP4. Kỳ vọng:

- case `completed`;
- bid opening record;
- evaluation handoff chứa official artifact, submission IDs và artifact index;
- `evaluation-handoff.json` trong MinIO;
- các hành động thủ công xuất hiện tại `/audit`.

## Negative checks bắt buộc

- `an.nguyen` tự xác minh intake → 409.
- `an.nguyen` tự quyết approval CP1/CP2 → 409.
- chạy case khi chưa xác minh → 409.
- còn câu hỏi blocking → không sinh approval CP1.
- upload file vượt giới hạn/sai extension → 4xx.
- ghi publication trước official package → 409.
- upload submission trước publication → 409.
- `an.nguyen` tự CP4 → 409.
- tenant Beta không đọc được case Alpha.

## Cách trình bày với lãnh đạo

Tập trung vào bốn bằng chứng: worker biết dừng khi thiếu dữ liệu; con người giữ
quyền quyết định; mọi file có hash/version; audit chỉ rõ ai làm gì. Luôn nói rõ
connector bên ngoài đang là upload-only, không mô tả nó như ERP/portal thật.
