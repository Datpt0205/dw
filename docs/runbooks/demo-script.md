# Demo DW01 — 3 phút

**An** đề nghị mua sắm (không có quyền duyệt). **Chi** trưởng ban, duyệt mọi checkpoint.

Chuẩn bị: `bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh`

> **Cách chia thời gian.** Luồng tạo HSMT là thứ *tất nhiên phải chạy được* — cho nó
> 30 giây rồi đi tiếp. Hai phút rưỡi còn lại dành cho những thứ người xem không
> đoán trước được. Ai cũng tin AI viết được cái hồ sơ; không ai tin nó **bắt lỗi
> chính mình** và **biết khi nào phải im lặng**.

---

## 0:00 — 0:30 · Luồng chính, chạy một mạch

An nhắn một dòng:

```
Cần mua 200 màn hình cho team AI FDX, 300 tỷ, trong 90 ngày, giao kho Hà Nội,
mời Thiết bị Việt, Minh Long với Sao Mai
```

→ đủ thông tin ngay, thẻ tóm tắt hiện ra. An: `đồng ý` → hồ sơ tạo.

Chi: `xác minh` → DW01 chạy, dừng ở CP1 → Chi: `duyệt cp1` → dựng HSMT → `duyệt cp2`
→ **RFQ tự phát hành qua email.**

*Nói một câu rồi đi tiếp:* "Ngưỡng 300 tỷ, hình thức đấu thầu, số nhà thầu tối
thiểu — đều lấy từ rule pack, model không tự nghĩ ra con số nào."

---

## 0:30 — 1:10 · Hỏi luật, và biết khi nào phải im ⭐

```
gói này phải cho nhà thầu bao nhiêu ngày chuẩn bị hồ sơ?
```

→ trích **nguyên văn** trong «…», kèm tên file và phiên bản. Trả lời được cả khi
câu hỏi thiếu ngữ cảnh: nêu đủ ba mốc 18 / 35 / 05 ngày rồi hỏi lại gói này theo
hình thức nào.

Rồi hỏi một điều **không có trong kho**:

```
Điều 20 Luật Đấu thầu quy định gì về bảo lãnh dự thầu?
```

→ *"Điều 20 trong đoạn trích không quy định về bảo lãnh dự thầu…"* — nói thẳng là
không có, chỉ sang điều đúng.

> **Điểm nói (business):** đây là chỗ mọi chatbot pháp lý gãy — nói trôi chảy mà
> sai điều luật. Một câu tư vấn sai về đấu thầu không phải lỗi kỹ thuật, nó là hồ
> sơ bị huỷ. DW01 chỉ được phép trả lời từ đoạn đã truy được; không truy được thì
> không có câu trả lời.

---

## 1:10 — 2:00 · Nó tự soi lại chính nó ⭐⭐ *(màn đắt nhất)*

```
hồ sơ này phát hành được chưa?
```

→ không phải câu trả lời "rồi/chưa", mà là một **bản rà soát**:

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

> **Điểm nói (business):** cái CHẶN kia là lỗi thật sự đắt trong đấu thầu — ký
> duyệt bản v6 rồi phát hành bản v7. Không ai cố ý làm; nó xảy ra vì một addendum
> chen vào giữa. Con người rất khó bắt, vì hai bản trông y hệt nhau.
>
> Hai dòng RỦI RO là **phản biện**, không phải kết luận: hệ thống không nói tiêu
> chí sai, nó nói *chưa thấy căn cứ* và cần ai xác nhận. Chặn thì theo rule pack,
> phản biện thì theo model — và phản biện **không bao giờ** tự chuyển thành chặn.

---

## 2:00 — 2:30 · Ai được ký, và cái gì được nhìn ⭐

Chi: `có những hồ sơ gì đang cần tôi duyệt` → **chỉ** hồ sơ thuộc thẩm quyền Chi;
hồ sơ của vai khác ghi rõ đang chờ ai.

Chi: `duyệt hồ sơ do Lê Thu Hà yêu cầu` → trúng đúng hồ sơ **bằng tên người đề
nghị**, không cần mã, không cần tên gói.

Chi: `duyệt` (trống) → *"Đang chờ 2 mục… bạn nói rõ hồ sơ nào"* — **không tự chọn.**

An hỏi cùng câu `tình hình chung thế nào?` → chỉ thấy hồ sơ của chính An.

An thử `duyệt cp1 luôn đi cho nhanh` → **bị chặn.**

> **Điểm nói (business):** ba câu này là ba câu kiểm toán viên sẽ hỏi. Cái nhìn
> thấy và cái ký được là **cùng một nguồn** — nên không có chuyện mời người ta bấm
> rồi báo lỗi. Và ẩn nút không phải phân quyền: chặn nằm ở chỗ ghi dữ liệu.

---

## 2:30 — 3:00 · Nhà cung cấp nộp mail, rồi tự sang bước chấm ⭐

Reply đúng thư RFQ, đính kèm 1 file. Trong ~20s: vào sổ tiếp nhận, biên nhận có
timestamp + hash, reply xác nhận cho NCC, báo Chi đã có hồ sơ về.

Chi: `xác nhận mở thầu` →

```
✅ CP4 hoàn tất — biên bản mở thầu đã lập, gói bàn giao đã niêm phong.
➡️ DW02 đã nhận 3 hồ sơ dự thầu cùng HSMT chính thức và bắt đầu chấm
   theo tiêu chí đã duyệt.
```

> **Điểm nói (business, câu chốt):** từ một dòng chat của An tới bảng chấm điểm có
> căn cứ — **không ai copy một file nào**. Biên bản mở thầu liệt kê từng hồ sơ kèm
> hash và giờ nhận, ai đối chiếu lại cũng ra đúng con số đó. Và HSMT bàn giao là
> **bản đã được duyệt**, không phải bản dựng lại từ trạng thái hiện tại.

---

## Nếu còn thời gian / bị hỏi thêm

- **Lan man rồi quay lại:** An đang khai dở, hỏi chuyện khác, rồi `thôi làm nốt cái
  bàn phím đi` → ghép đúng hồ sơ cũ, dữ liệu còn nguyên. Ngữ cảnh nằm ở Postgres,
  không phải "trí nhớ" của model.
- **Web — «Vết thực thi»:** mỗi bước dùng RAG có badge *n căn cứ*, bấm vào đọc được
  file nào / phiên bản nào / đoạn trích nguyên văn. Bước không dùng RAG ghi rõ
  "chạy deterministic".
- **Đổi ngưỡng:** gói 8 triệu thì chuyên gia ký cả hai checkpoint; 300 tỷ thì CP2
  lên trưởng ban. Sửa một dòng YAML, không đụng code — và mọi run đóng dấu
  `policy_version` để về sau còn truy được.

---

## Ghi chú cho người chạy demo

`scripts/chat_scenarios.py` chạy đúng những cảnh trên bằng model thật (không mock)
và tự chấm PASS/FAIL — chạy trước khi lên sân khấu:

```bash
bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh
docker compose --env-file .env -f infra/compose/docker-compose.yml \
    exec -T api python - < scripts/chat_scenarios.py
```
