# Demo DW01 — 3 phút, một mạch

**An** đề nghị mua sắm (không quyền duyệt). **Chi** trưởng ban, duyệt mọi checkpoint.
Kênh: Zalo, hai máy.

```bash
bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh
```

Câu chữ chính xác nằm ở [demo-lines.yaml](demo-lines.yaml) — file này giải thích *tại
sao*, không chép lại *gõ gì*. Chạy teleprompter để khỏi copy-dán:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1            # Enter → dòng kế lên clipboard
powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1 -Only chi  # chỉ phần của Chi (máy thứ hai)
powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1 -Auto      # tự dán + gửi vào cửa sổ đang focus
powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1 -From 9    # quay lại giữa chừng sau khi retake
```

> `-ExecutionPolicy Bypass` là bắt buộc trên máy đặt policy mặc định (`Restricted`).
> Nó chỉ áp cho tiến trình đó, không đổi cấu hình máy.

> Zalo Bot API chỉ nói được với tư cách **bot**, không đăng được tin nhắn thay tài
> khoản người. Nên bong bóng chat của An bắt buộc phải gửi từ máy An — script chỉ bỏ
> khâu copy-dán, không giả lập được.

---

## Nguyên tắc dựng

**Một hồ sơ duy nhất, không rẽ nhánh.** Mọi tình huống khó xảy ra **ngay trong lúc
chạy luồng chính**, đúng như ngoài đời: An gõ nhầm rồi sửa, hỏi lạc đề rồi quay lại,
sốt ruột đòi tự duyệt, đổi ý khi sếp chưa kịp ký. Không có cảnh nào phải mở hồ sơ
thứ hai để minh hoạ.

**Đừng dành thời gian cho thứ ai cũng tin.** Ai cũng tin AI viết được cái hồ sơ. Không
ai tin nó **chịu trách nhiệm với cái nó viết** — sửa được khi sai, tự bắt lỗi chính
mình, biết mình không được phép làm gì. Đó là chỗ đáng 3 phút.

---

## Chín cảnh

| # | Ai | Chuyện gì xảy ra | Vì sao đáng xem |
|---|---|---|---|
| 1 | An | Một dòng, đủ thông tin — nhưng gõ **2000** thay vì 200, rồi sửa | Sửa ngay trong luồng, không khai lại |
| 2 | An | Hỏi luật giữa chừng rồi `đồng ý` | Ba mốc 18/35/05 ngày, **không đoán**; hồ sơ dở không mất |
| 3 | An | `duyệt cp1 luôn đi cho nhanh` | Bị chặn — ẩn nút không phải phân quyền |
| 4 | Chi/An | Xác minh → trả lời làm rõ → CP1 | Luồng chính, cho nó chạy nhanh |
| 5 | Chi | Gõ `duyệt` trống | Liệt kê 3 mục rồi **hỏi lại**; chỉ hồ sơ bằng **tên người đề nghị** |
| 6 | An | Đổi thời hạn khi **CP2 đang chờ ký** ⭐⭐ | Thu hồi phiếu, báo Chi, **chạy lại toàn bộ** |
| 7 | Chi | `phát hành được chưa?` ⭐⭐⭐ | Bản rà soát có điểm; CHẶN tách khỏi RỦI RO |
| 8 | Chi | Ký lại → phát hành | RFQ tự gửi email; hạn nộp thầu đặt theo luật |
| 9 | An/Chi | Gia hạn **sau khi đã mời thầu** ⭐⭐ | Cùng câu nói, **đường khác**; addendum có hiệu lực thật |

---

## Ba điểm nói (business)

**Cảnh 6 — thu hồi phiếu.** Hầu hết hệ thống chọn cách dễ: cho sửa, giữ nguyên phiếu
duyệt. Nghĩa là người ký đang cầm một tờ mô tả con số không còn tồn tại. DW01 thu hồi
phiếu, báo người đang cầm nó, rồi chạy lại **toàn bộ** phép kiểm — vì hình thức mua
sắm, tiêu chí, cả bộ HSMT đều suy ra từ con số vừa đổi. Một phê duyệt cũ không được
phép đi theo sang bản mới.

**Cảnh 7 — tự soi.** Bản rà soát tách hai loại: **CHẶN** đến từ rule pack (vd đã ký
duyệt bản v6 rồi định phát hành bản v7 — lỗi đắt nhất trong đấu thầu, và người rất khó
bắt vì hai bản trông y hệt nhau), còn **RỦI RO** là phản biện của model, nói *chưa thấy
căn cứ* chứ không kết luận. Phản biện **không bao giờ** tự biến thành chặn.

**Cảnh 9 — cùng câu nói, đường khác.** Trước CP2 thì sửa thẳng, vì chưa ai bên ngoài
nhìn thấy. Sau khi đã mời thầu, đúng câu đó của An lại thành **đề nghị** gửi sang mua
sắm — addendum là văn bản của bên mời thầu gửi cho *tất cả* nhà thầu, một thay đổi mà
chỉ vài nhà thầu biết là gói thầu hỏng về mặt pháp lý. Và nó có hiệu lực **thật**: email
tới đúng ba nhà cung cấp đã mời kèm biên nhận và message-id, hạn đóng sổ dời thật 10
ngày — không phải tờ giấy nói đã gia hạn trong khi hệ thống vẫn đóng sổ theo hạn cũ.

---

## Nếu còn thời gian / bị hỏi thêm

- **Lan man rồi quay lại:** đang khai dở, hỏi chuyện khác, rồi `thôi làm nốt cái bàn
  phím đi` → ghép đúng hồ sơ cũ. Ngữ cảnh nằm ở Postgres, không phải "trí nhớ" của model.
- **Câu luật có tiền đề sai:** `Điều 20 Luật Đấu thầu quy định gì về bảo lãnh dự thầu?`
  → *"Điều 20 quy định về chỉ định thầu, không quy định về bảo lãnh dự thầu. Nội dung
  về bảo đảm dự thầu nằm tại Điều 43…"* — **sửa lại tiền đề** rồi chỉ sang điều đúng.
- **Phạm vi nhìn:** An hỏi `tình hình chung thế nào?` → chỉ thấy hồ sơ của chính An.
- **Web — «Vết thực thi»:** mỗi bước dùng RAG có badge *n căn cứ*, bấm vào đọc được file
  nào / phiên bản nào / đoạn trích nguyên văn. Bước không dùng RAG ghi rõ "deterministic".
- **Đổi ngưỡng:** gói 8 triệu thì chuyên gia ký cả hai checkpoint; 300 tỷ thì CP2 lên
  trưởng ban. Một dòng YAML, không đụng code — mọi run đóng dấu `policy_version`.
- **Nhà cung cấp nộp mail → DW02:** reply đúng thư RFQ kèm file → vào sổ tiếp nhận
  (~20s), biên nhận có timestamp + hash. Chi `xác nhận mở thầu` → biên bản mở thầu,
  gói bàn giao niêm phong, DW02 bắt đầu chấm. *Chưa chạy lại trong lần kiểm gần nhất —
  tổng duyệt trước nếu định đưa vào.*

---

## Tránh trong lúc quay

- **Đừng trả lời câu hỏi lại bằng số.** Bot hỏi *"Bạn đang nói về hồ sơ nào?"* mà gõ `1`
  thì nó mất ý định ban đầu và hỏi lại tiếp. Gõ nguyên câu có tên hồ sơ.
- **Luôn nêu tên hồ sơ.** `gia hạn 10 ngày` một mình là hên xui; câu đầy đủ thì chắc.
- **Đừng nhắc lại tên hàng khi sửa số.** `à nhầm, 200 thôi` giữ nguyên mô tả; còn
  `à nhầm, 200 màn hình thôi` khiến tiêu đề hồ sơ rút lại thành "Mua màn hình".
- **Đừng hỏi Chi "có đề nghị sửa đổi nào chờ tôi không"** — danh sách đang chờ mới chỉ
  gồm phiếu checkpoint, chưa gồm đề nghị addendum.

**Phát hiện mua lặp** và **cảnh báo khi văn bản luật thay đổi** đã có phần lõi nhưng
chưa nối vào luồng — đừng dựng cảnh quanh chúng.

---

## Trước khi lên sân khấu

Dữ liệu phải sạch — với **một** hồ sơ đang chờ thì `duyệt` trống sẽ hành động luôn thay
vì hỏi lại (đúng thiết kế, nhưng mất cảnh 5).

```bash
bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh
docker compose --env-file .env -f infra/compose/docker-compose.yml \
    exec -T api python - < scripts/chat_scenarios.py
```

`chat_scenarios.py` chạy 18 cảnh bằng model thật và tự chấm PASS/FAIL. Riêng chuỗi
chín cảnh ở trên đã được chạy liền một mạch trên hồ sơ thật: **16/16**.
