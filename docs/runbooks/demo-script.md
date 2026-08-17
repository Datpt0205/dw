# Demo DW01 — hai người, một Digital Worker

**An** đề nghị mua sắm (không có quyền duyệt). **Chi** trưởng ban, duyệt mọi checkpoint.

Chuẩn bị: `bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh`

## 1. An mở nhu cầu — một dòng là đủ

```
Cần mua 200 màn hình cho team AI FDX, 300 tỷ, trong 90 ngày, giao kho Hà Nội,
mời Thiết bị Việt, Minh Long với Sao Mai
```

→ đủ thông tin ngay, bot đưa thẳng thẻ tóm tắt. An nhắn `đồng ý` (hay `ok tạo đi`,
`chuẩn rồi` — không có từ khoá nào cả) → hồ sơ tạo.

> Suy luận hiện ngay trên câu trả lời (dòng gạch `┆`): **300 tỷ > 5 tỷ → Đấu thầu,
> tối thiểu 3 nhà thầu.** Ngưỡng lấy từ rule pack, không phải model tự nghĩ.

## 2. An hỏi luật ⭐

```
gói này thì bên mình phải cho nhà thầu bao nhiêu ngày chuẩn bị hồ sơ?
```

→ bot **truy kho tài liệu thật**, trả lời kèm trích nguyên văn trong «…» và ghi rõ
tên file + phiên bản.

Rồi hỏi một điều không có trong kho:

```
Điều 20 Luật Đấu thầu nói gì?
```

→ nếu không truy được, bot nói thẳng **không tìm thấy** thay vì trả lời từ trí nhớ.

> **Điểm nói:** đây là chỗ mọi chatbot pháp lý gãy — nói trôi chảy mà sai điều luật.
> DW01 chỉ được phép trả lời từ đoạn đã truy được; không có đoạn thì không có câu
> trả lời. Và kho tài liệu lọc theo quyền của chính người hỏi.

## 3. An bị cắt ngang — và quay lại ⭐

Đang khai dở một yêu cầu khác, An hỏi linh tinh:

```
à mà chiều nay họp giao ban mấy giờ nhỉ
```

→ từ chối lịch sự, **không bóc gì vào hồ sơ**. Rồi An quay lại:

```
thôi làm nốt cái bàn phím đi
```

→ ghép đúng hồ sơ đang treo, thông tin đã khai còn nguyên.

> **Điểm nói:** ngữ cảnh nằm ở state hội thoại trong Postgres, không phải "trí nhớ"
> của model. Lan man bao nhiêu lượt cũng không trôi.

## 4. Chi hỏi chéo ⭐

Chi mở Zalo, hỏi mơ hồ đúng kiểu sếp — không mã hồ sơ, không tên gói:

```
có những hồ sơ gì đang cần tôi duyệt
```

→ chỉ liệt kê hồ sơ **thuộc thẩm quyền Chi**; hồ sơ của vai khác ghi rõ đang chờ ai.

```
duyệt hồ sơ do Lê Thu Hà yêu cầu
```

→ chỉ đúng hồ sơ bằng **tên người đề nghị**, không cần mã, không cần tên gói.

Đối chứng ngay tại chỗ — **An hỏi câu tương tự**:

```
tình hình chung thế nào?
```

→ An **chỉ thấy hồ sơ do chính An đề nghị**. Hồ sơ khác không hề vào prompt, nên
model không có gì để lỡ miệng.

> **Điểm nói:** phạm vi nhìn do code quyết theo scope, không phải model tự chọn kể
> gì. Và cái Chi thấy là cái Chi ký được — danh sách đọc cùng một dấu thẩm quyền mà
> lệnh duyệt kiểm.

## 5. An thử vượt quyền

```
duyệt cp1 luôn đi cho nhanh
```

→ **bị chặn.** An không có quyền quyết định, và bot không "duyệt hộ".

> **Điểm nói:** ẩn nút không phải phân quyền. Chặn nằm ở chỗ ghi dữ liệu, nên gọi
> thẳng API cũng vậy.

## 6. Chi thẩm định và ký

Chi nhận thẻ xác minh đầu vào, nhắn `xác minh` → DW01 chạy: đọc yêu cầu → **truy quy
chế công ty và Luật Đấu thầu** → lập phương án → dừng ở CP1 với vài câu hỏi thương
mại. An thấy từng bước chạy qua chat.

**An** trả lời gộp trong chat của mình:

```
bảo hành 36 tháng, kèm đào tạo vận hành, thanh toán sau nghiệm thu 30 ngày
```

(hoặc lười: `cứ lấy theo gợi ý nhé`) → tự chạy tiếp tới CP1.

Chi nhận **thẻ CP1** — phương án, trích đoạn điều luật truy được, dòng đối chiếu
«Hạn nộp X ngày ≥ tối thiểu 18 ngày theo Điều 45» — rồi `duyệt cp1`.

→ DW01 dựng HSMT: tiêu chí có trọng số, shortlist NCC, rà rủi ro → CP2 → `duyệt cp2`

→ **RFQ tự phát hành qua email ngay khi CP2 được duyệt** — không ai bấm thêm gì.

> **Điểm nói:** gói 300 tỷ vượt ngưỡng 500 triệu nên rule pack đưa CP2 lên trưởng
> ban. Gói 8 triệu thì chuyên gia ký cả hai. Đổi ngưỡng là sửa một dòng YAML, không
> đụng code — và mọi run đều đóng dấu `policy_version` để về sau còn truy được.

## 7. Nhà cung cấp nộp hồ sơ qua email

Mở hộp mail đã nhận RFQ `[MỜI CHÀO GIÁ][DW01:<case>]` → **reply đúng thư đó, đính
kèm 1 file**.

Trong ~20s: ghi sổ tiếp nhận, lập biên nhận (timestamp + hash), reply xác nhận cho
NCC, và báo Chi đã có hồ sơ về. Không ai upload tay.

Demo cấu hình đủ 1 hồ sơ là chốt (`DW_SUBMISSIONS_MIN_TO_CLOSE=1`) → thẻ CP4 tới
Chi. Không cấu hình thì hồ sơ tự chốt khi hết hạn nộp, kể cả thiếu nhà thầu — và nói
rõ thiếu bao nhiêu:

```
xác nhận mở thầu
```

→ biên bản mở thầu tự lập — **liệt kê từng hồ sơ kèm hash và giờ nhận**, ai đối
chiếu lại cũng ra đúng con số đó — rồi gói bàn giao DW02 niêm phong. Hết luồng DW01.

## 8. Web — nơi chứng kiến

Mở hồ sơ → khối **«Vết thực thi»**:

- Mỗi bước dùng RAG có badge **n căn cứ** → bấm vào đọc được: file nào, phiên bản
  nào, % liên quan, đoạn trích nguyên văn.
- Dòng «Ràng buộc bóc từ căn cứ: thời gian chuẩn bị HSDT tối thiểu 18 ngày (Điều
  45)» — LLM bóc số từ đúng đoạn luật vừa truy, **code xác minh nguyên văn** rồi mới
  áp vào tiến độ. Không truy được thì dùng mặc định rule pack, không bịa.
- Bước không dùng RAG ghi rõ "chạy deterministic".
- Timeline: ai làm gì lúc nào — An khai, Chi xác minh và duyệt CP1/CP2.

---
