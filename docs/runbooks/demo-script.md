# Demo DW01 — 3 phút

**An** đề nghị mua sắm (không quyền duyệt). **Chi** trưởng ban, duyệt mọi checkpoint.
Kênh: Zalo.

Chuẩn bị: `bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh`

> **Cách chia thời gian.** Luồng tạo HSMT là thứ *tất nhiên phải chạy được* — 25 giây
> rồi đi tiếp. Ai cũng tin AI viết được cái hồ sơ. Không ai tin nó **chịu trách nhiệm
> với cái nó viết**: sửa được khi sai, tự bắt lỗi chính mình, biết mình không được
> phép làm gì. Đó là hai phút rưỡi còn lại.
>
> Cả demo chạy trên **một hồ sơ duy nhất** — người xem theo được một câu chuyện,
> không phải sáu tính năng rời.

---

## 0:00 — 0:25 · Luồng chính, một mạch

An:

```
Cần mua 200 màn hình cho team AI FDX, 300 tỷ, trong 90 ngày, giao kho Hà Nội,
mời Thiết bị Việt, Minh Long với Sao Mai
```

→ đủ thông tin ngay, thẻ tóm tắt hiện ra. An: `đồng ý` → hồ sơ tạo, chuyển Chi xác minh.

Chi: `xác minh hồ sơ màn hình cho team AI FDX` → DW01 chạy, dừng ở làm rõ.
An: `cứ lấy theo gợi ý nhé` → chạy tiếp, dừng ở **CP1**.
Chi: `duyệt cp1` → dựng HSMT + tiêu chí → dừng ở **CP2**.

*Nói một câu rồi đi tiếp:* "Ngưỡng 300 tỷ, hình thức đấu thầu, số nhà thầu tối
thiểu, số ngày cho nhà thầu chuẩn bị — đều lấy từ rule pack và từ điều luật truy
được. Model không tự nghĩ ra con số nào."

⏱ *Mỗi lần chạy mất 20–40 giây. Cắt dựng, hoặc nói phần trên trong lúc chờ.*

---

## 0:25 — 0:55 · Đổi ý, ở hai mức giá ⭐⭐

**Mức rẻ — gõ nhầm lúc đang khai.** (mở nhanh một khung chat khác)

```
cần mua 2000 laptop cho khối kinh doanh, 50 tỷ, trong 60 ngày, giao kho Hà Nội,
mời FPT, CMC, Viettel
```
```
à nhầm, 200 laptop thôi không phải 2000
```

→ thẻ tóm tắt hiện lại với **200**, không phải khai lại từ đầu. PR lưu xuống ghi
`Số lượng: 200`.

**Mức đắt — hồ sơ đã trình CP2, Chi chưa ký.** Quay lại hồ sơ màn hình:

```
hồ sơ 200 màn hình cho tôi kéo dài thành 120 ngày nhé
```

→

```
✅ Đã sửa hồ sơ — hồ sơ «Mua 200 màn hình cho team AI FDX».
Đã báo người phụ trách xử lý tiếp.
```

Mở máy Chi cho thấy: **phiếu CP2 cũ đã bị thu hồi**, kèm thông báo
*"⚠️ Hồ sơ vừa được sửa — thu hồi phiếu CP2"*, và hồ sơ **chạy lại từ đầu** rồi
trình phiếu mới.

> **Điểm nói (business):** đây là chỗ hầu hết hệ thống chọn cách dễ — cho sửa, giữ
> nguyên phiếu duyệt. Nghĩa là người ký đang cầm một tờ mô tả con số không còn tồn
> tại. DW01 **thu hồi phiếu**, báo cho người đang cầm nó, rồi **chạy lại toàn bộ
> phép kiểm** — vì hình thức mua sắm, tiêu chí, cả bộ HSMT đều suy ra từ con số vừa
> đổi. Một phê duyệt cũ không được phép đi theo sang bản mới.

---

## 0:55 — 1:35 · Nó tự soi lại chính nó ⭐⭐⭐ *(màn đắt nhất)*

Sau khi Chi `duyệt cp1` lại và hồ sơ lên CP2, Chi hỏi:

```
hồ sơ này phát hành được chưa?
```

→ không phải "rồi/chưa", mà là một **bản rà soát có điểm số**:

```
🛑 CHƯA PHÁT HÀNH ĐƯỢC — Mua 200 màn hình cho team AI FDX
Điểm: 65/100

CHẶN (1):
1. «solicitation_package» đã đổi sau khi niêm phong
   Bản niêm phong dùng v6, hiện tại đã là v7. Phê duyệt đang gắn với v6,
   không được dùng để phát hành bản mới.

RỦI RO (2):
1. Tổ hợp thông số có thể thu hẹp cạnh tranh
2. Tiêu chí "thiết kế hiện đại" không có cách đo
```

> **Điểm nói (business):** cái CHẶN kia là lỗi đắt nhất trong đấu thầu — ký duyệt
> bản v6 rồi phát hành bản v7. Không ai cố ý; nó xảy ra vì một thay đổi chen vào
> giữa. Người rất khó bắt, vì hai bản trông y hệt nhau.
>
> Hai dòng RỦI RO là **phản biện**, không phải kết luận: hệ thống không nói tiêu chí
> sai, nó nói *chưa thấy căn cứ* và cần người xác nhận. Chặn thì theo rule pack,
> phản biện thì theo model — và phản biện **không bao giờ** tự biến thành chặn.

---

## 1:35 — 2:05 · Ai được ký, ai nhìn thấy gì ⭐

Bốn câu, nhanh:

| Ai | Nhắn | Kết quả |
|---|---|---|
| Chi | `duyệt` | *"Đang chờ 2 mục… bạn nói rõ hồ sơ nào"* — **không tự chọn** |
| Chi | `duyệt hồ sơ do Lê Thu Hà yêu cầu` | trúng đúng hồ sơ **bằng tên người đề nghị** |
| An | `tình hình chung thế nào?` | chỉ thấy hồ sơ của chính An |
| An | `duyệt cp1 luôn đi cho nhanh` | **bị chặn** |

Chèn thêm một câu hỏi luật có **tiền đề sai**:

```
Điều 20 Luật Đấu thầu quy định gì về bảo lãnh dự thầu?
```

→ *"Điều 20 quy định về chỉ định thầu, không quy định về bảo lãnh dự thầu. Nội dung
về bảo đảm dự thầu nằm tại Điều 43…"* — **sửa lại tiền đề của câu hỏi** rồi chỉ sang
điều đúng, kèm trích nguyên văn.

> **Điểm nói (business):** ba câu đầu là ba câu kiểm toán viên sẽ hỏi. Cái *nhìn
> thấy* và cái *ký được* lấy từ **cùng một nguồn** — nên không có chuyện mời người ta
> bấm rồi báo lỗi. Ẩn nút không phải phân quyền: chặn nằm ở chỗ ghi dữ liệu.
>
> Câu luật là chỗ mọi chatbot pháp lý gãy — nói trôi chảy mà sai điều. Một câu tư vấn
> sai về đấu thầu không phải lỗi kỹ thuật, nó là hồ sơ bị huỷ.

---

## 2:05 — 2:40 · Sau khi đã ra ngoài, sửa đổi vẫn có hiệu lực thật ⭐⭐

Chi: `duyệt cp2 hồ sơ màn hình team AI FDX` → niêm phong bản chính thức,
**RFQ tự phát hành qua email** tới ba nhà cung cấp. Hạn nộp thầu được đặt ngay lúc
này, tính từ số ngày tối thiểu bóc ra từ luật.

An đổi ý lần nữa — nhưng lần này hồ sơ **đã ra khỏi công ty**:

```
hồ sơ màn hình team AI FDX gia hạn nộp thầu thêm 10 ngày giúp tôi
```

→ *"Mình đã chuyển đề nghị… tới bộ phận mua sắm xem xét."* — An **không tự sửa được
nữa**. Thẻ đề nghị bay sang Chi.

Chi: `lập addendum cho hồ sơ màn hình, gia hạn nộp thầu thêm 10 ngày` → `duyệt cp3`

```
✅ Đã duyệt CP3 — addendum có hiệu lực.

Đã gửi sửa đổi tới: Thiết bị Việt, Minh Long, Sao Mai.
Hạn nộp thầu lùi 10 ngày → 20/09/2026.
```

> **Điểm nói (business):** trước CP2 thì sửa thẳng, vì chưa ai bên ngoài nhìn thấy.
> Sau khi đã mời thầu thì **cùng một câu nói của An lại đi một đường khác** — thành
> đề nghị, vì addendum là văn bản của bên mời thầu gửi cho *tất cả* nhà thầu. Một
> thay đổi mà chỉ vài nhà thầu biết là gói thầu hỏng về mặt pháp lý.
>
> Và nó **có hiệu lực thật**: email đi tới đúng danh sách đã mời, có biên nhận và
> message-id; hạn đóng sổ dời thật 10 ngày. Không phải một tờ giấy nói là đã gia hạn
> trong khi hệ thống vẫn đóng sổ theo hạn cũ.

---

## 2:40 — 3:00 · Nhà cung cấp nộp mail, rồi tự sang bước chấm

Reply đúng thư RFQ, đính kèm 1 file. Trong ~20s: vào sổ tiếp nhận, biên nhận có
timestamp + hash, reply xác nhận cho NCC, báo Chi đã có hồ sơ về.

Chi: `xác nhận mở thầu` →

```
✅ CP4 hoàn tất — biên bản mở thầu đã lập, gói bàn giao đã niêm phong.
➡️ DW02 đã nhận 3 hồ sơ dự thầu cùng HSMT chính thức và bắt đầu chấm
   theo tiêu chí đã duyệt.
```

> **Điểm nói (câu chốt):** từ một dòng chat của An tới bảng chấm điểm có căn cứ —
> **không ai copy một file nào**. Biên bản mở thầu liệt kê từng hồ sơ kèm hash và giờ
> nhận. Và HSMT bàn giao là **bản đã được duyệt**, không phải bản dựng lại từ trạng
> thái hiện tại.

---

## Nếu còn thời gian / bị hỏi thêm

- **Lan man rồi quay lại:** An đang khai dở, hỏi chuyện khác, rồi `thôi làm nốt cái
  bàn phím đi` → ghép đúng hồ sơ cũ, dữ liệu còn nguyên. Ngữ cảnh nằm ở Postgres,
  không phải "trí nhớ" của model.
- **Hỏi luật giữa lúc đang khai:** hỏi xong quay lại khai tiếp, hồ sơ dở **không mất**.
- **Web — «Vết thực thi»:** mỗi bước dùng RAG có badge *n căn cứ*, bấm vào đọc được
  file nào / phiên bản nào / đoạn trích nguyên văn. Bước không dùng RAG ghi rõ
  "chạy deterministic".
- **Đổi ngưỡng:** gói 8 triệu thì chuyên gia ký cả hai checkpoint; 300 tỷ thì CP2 lên
  trưởng ban. Sửa một dòng YAML, không đụng code — mọi run đóng dấu `policy_version`.

---

## Tránh trong lúc quay

Ba chỗ chưa xong, đừng đi vào:

- **Đừng trả lời câu hỏi lại bằng số.** Khi bot hỏi *"Bạn đang nói về hồ sơ nào?"* mà
  gõ `1` thì nó mất ý định ban đầu và hỏi lại tiếp. Gõ nguyên câu có tên hồ sơ.
- **Nêu tên hồ sơ trong câu, đừng nói cộc lốc.** `gia hạn 10 ngày` một mình là hên
  xui; `hồ sơ màn hình team AI FDX gia hạn nộp thầu thêm 10 ngày` thì chắc chắn trúng.
- **Đừng hỏi Chi "có đề nghị sửa đổi nào chờ tôi không"** — danh sách đang chờ chỉ
  liệt kê phiếu checkpoint, chưa gồm đề nghị addendum.

Ngoài ra: **phát hiện mua lặp** và **cảnh báo khi văn bản luật thay đổi** đã có phần
lõi nhưng chưa nối vào luồng — không đưa vào demo.

---

## Ghi chú cho người chạy demo

`scripts/chat_scenarios.py` chạy 18 cảnh trên bằng model thật (không mock) và tự chấm
PASS/FAIL. Chạy trước khi lên sân khấu — dữ liệu phải sạch, vì với **một** hồ sơ đang
chờ thì `duyệt cp2` trống sẽ hành động luôn thay vì hỏi lại (đúng thiết kế, nhưng mất
cảnh 1:35):

```bash
bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh
docker compose --env-file .env -f infra/compose/docker-compose.yml \
    exec -T api python - < scripts/chat_scenarios.py
```

Cảnh 0:25 (sửa hồ sơ đã trình CP2) và cảnh 2:05 (addendum có hiệu lực) không nằm
trong 18 cảnh đó — đã kiểm riêng trên hồ sơ thật, 5/5 và 6/6.
