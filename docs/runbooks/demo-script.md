# Demo DW01 — 3 phút, một mạch

**An** đề nghị mua sắm (không quyền duyệt) · **CHI** trưởng ban, duyệt mọi checkpoint.
Kênh: Zalo, hai máy.

Reset trước khi quay:

```bash
bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh
```

---

## Các câu, theo đúng thứ tự

**AN** — `Cần mua 2000 màn hình cho team AI FDX, 300 tỷ, trong 90 ngày, giao kho Hà Nội, mời Thiết bị Việt, Minh Long với Sao Mai`

**AN** — `à nhầm, 200 thôi không phải 2000 nhé`

**AN** — `mà gói cỡ này luật bắt cho nhà thầu bao nhiêu ngày chuẩn bị hồ sơ?`

**AN** — `đồng ý`

**AN** — `duyệt cp1 luôn đi cho nhanh`

**CHI** — `xác minh hồ sơ màn hình cho team AI FDX`

**AN** — `cứ lấy theo gợi ý nhé` ⏳ *chờ ~25s*

**CHI** — `duyệt`

**CHI** — `duyệt cp1 hồ sơ do An đề nghị` ⏳ *chờ ~30s*

**AN** — `hồ sơ màn hình team AI FDX cho tôi kéo dài thành 120 ngày nhé` ⏳ *chờ ~35s*

**CHI** — `hồ sơ màn hình team AI FDX phát hành được chưa?`

**CHI** — `duyệt cp1 hồ sơ màn hình team AI FDX` ⏳ *chờ ~30s*

**CHI** — `duyệt cp2 hồ sơ màn hình team AI FDX` ⏳ *chờ ~30s*

**AN** — `hồ sơ màn hình team AI FDX gia hạn nộp thầu thêm 10 ngày giúp tôi`

**CHI** — `lập addendum cho hồ sơ màn hình team AI FDX, gia hạn nộp thầu thêm 10 ngày`

**CHI** — `duyệt cp3 hồ sơ màn hình team AI FDX`

Ba chỗ ⏳ là bắt buộc chờ — gõ dòng kế sớm quá thì hồ sơ chưa tới trạng thái đúng và
câu sẽ trượt.

---

## Nếu còn thời gian

**AN hoặc CHI** — `Điều 20 Luật Đấu thầu quy định gì về bảo lãnh dự thầu?`

**AN** — `tình hình chung thế nào?`

**AN** — `thôi làm nốt cái bàn phím đi` *(chỉ dùng được nếu trước đó có khai dở một
yêu cầu bàn phím)*

---

## Tránh trong lúc quay

- Bot hỏi *"Bạn đang nói về hồ sơ nào?"* — **đừng gõ `1`**, gõ nguyên câu có tên hồ sơ.
- **Luôn nêu tên hồ sơ.** `gia hạn 10 ngày` một mình là hên xui.
- **Đừng nhắc lại tên hàng khi sửa số.** `à nhầm, 200 thôi` giữ nguyên mô tả; còn
  `à nhầm, 200 màn hình thôi` khiến tiêu đề rút lại thành "Mua màn hình".
- **Đừng hỏi Chi "có đề nghị sửa đổi nào chờ tôi không"** — danh sách đang chờ mới chỉ
  gồm phiếu checkpoint.
- **Phát hiện mua lặp** và **cảnh báo văn bản luật thay đổi** chưa nối vào luồng.
- Cảnh **NCC nộp mail → DW02** cần reply email thật, chưa chạy lại trong lần kiểm gần nhất.

---

## Teleprompter (tuỳ chọn)

Tự copy từng câu vào clipboard, in điểm nói, tự canh giờ chờ:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1
powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1 -Only chi   # máy thứ hai
powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1 -From 9     # sau khi retake
```

Điểm nói từng cảnh nằm ở [demo-lines.yaml](demo-lines.yaml).

Chuỗi trên đã chạy liền một mạch trên hồ sơ thật: **16/16**.
