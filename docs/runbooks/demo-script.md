# Kịch bản demo & thuyết trình — Digital Worker (Đấu thầu DW01)

Tài liệu này gồm 3 phần: **(A) thông điệp/câu chuyện để present**, **(B) kịch bản
bấm từng bước trên UI**, **(C) mẹo trình bày**. Thời lượng gợi ý: **12–15 phút**.

---

## A. Câu chuyện để mở đầu (1–2 phút, nói không cần máy)

> "Đây là một **Digital Worker** — nhân sự số — cho nghiệp vụ **chuẩn bị hồ sơ đấu
> thầu**. Nó **đọc PR đã duyệt, tra cứu luật/quy chế, tự soạn phương án – hồ sơ mời
> thầu – tiêu chí chấm**, nhưng **không tự quyết**: mọi bước quan trọng đều **dừng
> lại chờ người có thẩm quyền phê duyệt** (human-in-command). Người phê duyệt được
> **nhắc qua Slack**, mọi thứ **truy vết được** và **cô lập theo từng đơn vị**."

3 điểm nhấn xuyên suốt — nhắc lại khi demo:
1. **Con người kiểm soát**: 4 chốt phê duyệt CP1→CP4, worker luôn dừng chờ người.
2. **Có căn cứ (RAG)**: mọi đề xuất kèm trích dẫn luật/quy chế đã nạp.
3. **An toàn đa đơn vị**: mỗi tổ chức chỉ thấy dữ liệu của mình; luật thì dùng chung.

---

## B. Kịch bản bấm trên UI

### 0. Chuẩn bị (trước khi lên sân khấu)
- Mở sẵn **http://localhost:3000** và **Slack** (để cạnh nhau — lát nữa Slack sẽ
  hiện thông báo trực tiếp trên màn hình).
- 3 tài khoản, mật khẩu `demo-password`, đều thuộc đơn vị **Alpha**:

  | Tài khoản   | Vai trò        | Dùng để trình |
  | ----------- | -------------- | ------------- |
  | `an.nguyen` | Chuyên viên    | tạo hồ sơ, chạy Digital Worker |
  | `binh.tran` | Người phê duyệt | duyệt CP1/CP2/CP3/CP4 |
  | `chi.le`    | Quản trị        | upload luật dùng chung, xem toàn quyền |

- **Mẹo vàng — Đổi tài khoản 1 chạm:** bấm vào **chip tên** (góc trên phải) → chọn
  **An / Bình / Chi** để nhảy vai **tức thì, không cần đăng nhập lại**. Đây là chìa
  khoá để demo luồng phê duyệt mượt.

### 1. Tổng quan — đăng nhập `an.nguyen` (1 phút)
1. Đăng nhập → vào **Trang chủ** (dashboard).
2. Chỉ nhanh: các thẻ **Hồ sơ đang xử lý / Chờ phê duyệt / Giá trị / Tài liệu**,
   danh sách **Hồ sơ cần chú ý**, **Cơ cấu loại gói thầu**.
3. Nói: *"Số liệu này lấy trực tiếp từ hồ sơ thật, không phải tĩnh."*

### 2. Nạp tri thức cho máy — RAG (2 phút)
> Nếu muốn ngắn gọn, có thể bỏ qua và nói "luật đã được nạp sẵn".

1. Đổi sang **`chi.le`** (chip tên → Chi). Vào **Tri thức**.
2. Bấm **Thêm tài liệu** → popup: chọn 1 file **PDF/DOCX/ảnh scan** luật đấu thầu,
   Loại **Pháp lý/Luật**, Phạm vi **Dùng chung toàn hệ thống** → **Tải lên và xử lý**.
3. Nói trong lúc chờ: *"Máy tự **OCR + bóc bảng**, cắt đoạn theo cấu trúc, nhúng bằng
   mô hình self-host BGE-M3 và lập chỉ mục — đây là nguồn để nó trích dẫn về sau."*
4. Xong: tài liệu hiện trong danh mục, badge **Toàn cục**.

### 3. Digital Worker chạy + chốt phê duyệt (6–7 phút) — phần chính
1. Đổi về **`an.nguyen`**. Vào **Xây hồ sơ thầu** → **Tạo hồ sơ**.
2. Trong popup: chọn file **PR đã duyệt** (có nút *Tải mẫu PR* nếu cần), điền Tên gói
   thầu / Mã PR / Giá trị / Thời hạn / Nhà cung cấp → **Tạo và gửi xác minh**.
3. **CHUYỂN SANG CỬA SỔ SLACK** ngay: **Bình nhận DM** "*Yêu cầu mới cần phê duyệt*"
   kèm nút **Mở hồ sơ DW01**.
   > 🎯 Khoảnh khắc "wow": *"Người tạo không tự duyệt hồ sơ của mình — hệ thống nhắc
   > đúng người phê duyệt qua Slack ngay lập tức."*
4. Đổi sang **`binh.tran`** (chip tên → Bình) → **Phê duyệt** (Inbox/Phê duyệt) để
   **xác minh intake**. Mở hồ sơ → bấm **Chạy** cho Digital Worker chạy graph:
   - Bóc yêu cầu → kiểm tra đủ → **đề xuất phương án mua sắm** (kèm trích dẫn luật/
     quy chế — chỉ ra mục *căn cứ pháp lý / căn cứ quy chế*).
   - Dừng ở **CP1 — Duyệt phương án**.
5. `binh.tran` **Duyệt CP1** → worker tự tiếp: dựng **Hồ sơ mời thầu**, **Tiêu chí
   chấm**, **Shortlist nhà cung cấp** (đều kèm *references* từ RAG) → dừng **CP2**.
6. `binh.tran` **Duyệt CP2** → **khoá bản chính thức**. Tiếp tục **CP3 (phát hành/
   công bố)** và **CP4 (bàn giao)** tương tự → trạng thái **Hoàn tất**.
7. Mỗi lần duyệt/từ chối, chỉ lại Slack: **An nhận DM kết quả**; nếu để quá hạn,
   **Chi nhận DM nhắc việc** (escalation).

### 4. Phân quyền & cô lập (1–2 phút)
1. Đổi qua lại **An ↔ Bình ↔ Chi**, chỉ: sidebar & nút **thay đổi theo vai** (chỉ
   Bình thấy nút Duyệt; chỉ Chi thấy Quản trị & upload luật global).
2. Nói: *"UI ẩn cho gọn, nhưng **backend mới là nơi chặn thật** — gọi thẳng API mà
   thiếu quyền vẫn 403. Dữ liệu mỗi đơn vị tách biệt bằng RLS; luật global thì chia sẻ."*

---

## C. Mẹo trình bày

- **Bố cục màn hình:** trình duyệt (trái) + Slack (phải) cùng lúc — để khán giả
  **thấy Slack nảy thông báo ngay khi bấm trên web**. Đây là điểm ấn tượng nhất.
- **Dùng account switcher**, đừng đăng xuất/đăng nhập lại — giữ nhịp demo liền mạch.
- **Kể theo vai người dùng**, không kể theo tính năng: "An tạo → Bình được nhắc →
  Bình duyệt → An biết kết quả". Người xem hiểu *quy trình*, không sa vào kỹ thuật.
- **Nhấn 3 lần** vào thông điệp: *người kiểm soát • có căn cứ • an toàn đa đơn vị*.
- **Nếu Slack không hiện:** kiểm tra `.env` có `DW_SLACK_APPROVALS_ENABLED=true` và
  3 `SLACK_USER_*_ID` đúng (member ID Slack, dạng `U…`), rồi
  `docker compose ... up -d worker`. Test nhanh không cần UI: tạo 1 hồ sơ → worker
  log `Slack approval notification sent`.
- **Câu chốt:** *"Digital Worker làm phần nặng và lặp lại, con người giữ quyền quyết
  định ở đúng 4 điểm — nhanh hơn nhưng vẫn kiểm soát và truy vết được."*

---

### Phụ lục — URL & lệnh nhanh
- Web `http://localhost:3000` · API `http://localhost:8000` · Keycloak `http://localhost:8686`
- Bật stack: `docker compose -f infra/compose/docker-compose.yml --env-file .env --profile full up -d`
- Đổi member ID Slack thật cho Bình/Chi: sửa `SLACK_USER_BINH_ID` / `SLACK_USER_CHI_ID`
  trong `.env` → `docker compose ... up -d worker` (không cần rebuild).
