# Demo DW01 — 3 phút một mạch, cộng 2 cảnh mới

**An** đề nghị mua sắm (không quyền duyệt) · **CHI** trưởng ban, duyệt mọi checkpoint.
Kênh: Zalo, hai máy — riêng cảnh 11 chạy trên web.

Cảnh 1–9 là mạch cũ, quay liền không dừng. Cảnh 10–11 là phần mới, có một lần dừng
máy ở giữa để gieo dữ liệu.

Reset trước khi quay:

```bash
bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh
```

Cảnh 10–11 cần một bước gieo **riêng, chạy giữa buổi** — xem mục dưới. Chạy sớm
thì An bị chặn ngay câu mở đầu.

---

## Các câu, theo đúng thứ tự

**AN** — `Cần mua 2000 màn hình cho team AI FDX, 300 tỷ, trong 90 ngày, giao kho Hà Nội, mời Thiết bị Việt, Minh Long với Sao Mai`

**AN** — `à nhầm, 200 thôi không phải 2000 nhé`

**AN** — `mà gói cỡ này luật bắt cho nhà thầu bao nhiêu ngày chuẩn bị hồ sơ?`

> 🆕 Câu trả lời giờ đi ra **web tại thời điểm hỏi**, không đọc kho đã ingest.
> Chỉ vào đường dẫn nguồn trong câu trả lời — đó là trang gốc, không phải bản
> chép trong hệ thống. Xem [§Hai thứ mới](#hai-thứ-mới-trong-bản-này).

**AN** — `đồng ý`

**AN** — `duyệt cp1 luôn đi cho nhanh`

**CHI** — `xác minh hồ sơ màn hình cho team AI FDX`

**AN** — `cứ lấy theo gợi ý nhé` ⏳ _chờ ~25s_

**CHI** — `duyệt`

**CHI** — `duyệt cp1 hồ sơ do An đề nghị` ⏳ _chờ ~30s_

**AN** — `hồ sơ màn hình team AI FDX cho tôi kéo dài thành 120 ngày nhé` ⏳ _chờ ~35s_

**CHI** — `hồ sơ màn hình team AI FDX phát hành được chưa?`

**CHI** — `duyệt cp1 hồ sơ màn hình team AI FDX` ⏳ _chờ ~30s_

**CHI** — `duyệt cp2 hồ sơ màn hình team AI FDX` ⏳ _chờ ~30s_

**AN** — `hồ sơ màn hình team AI FDX gia hạn nộp thầu thêm 10 ngày giúp tôi`

**CHI** — `lập addendum cho hồ sơ màn hình team AI FDX, gia hạn nộp thầu thêm 10 ngày`

**CHI** — `duyệt cp3 hồ sơ màn hình team AI FDX`

Ba chỗ ⏳ là bắt buộc chờ — gõ dòng kế sớm quá thì hồ sơ chưa tới trạng thái đúng và
câu sẽ trượt.

---

## Cảnh 10–11 — khi hồ sơ cứ phải chỉnh lại 🆕

**Dừng máy. Chạy một lệnh, rồi quay tiếp:**

```bash
bash scripts/seed_demo_rework.sh
```

Ngưỡng chặn là 5 lần bị trả trong 30 ngày. Diễn thật 5 lần mất khoảng 6 phút và
chẳng cho thấy gì — cái đáng quay là chuyện xảy ra **sau** khi chạm ngưỡng. Script
in ra đúng 5 lần đó để bạn đọc trên màn hình trước khi vào cảnh.

### Cảnh 10 · An mở hồ sơ mới — và bị giữ lại _(Zalo)_

**AN** — `Cần mua 40 bộ bàn ghế cho phòng họp tầng 3, 900 triệu, trong 45 ngày`

Bot **không** tạo hồ sơ. Nó trả lời nguyên văn:

> Hồ sơ gần đây phải chỉnh lại 5 lần trong 30 ngày. Bạn gửi phần mô tả bối cảnh
> để bên mua sắm xem và hỗ trợ, sau đó tạo hồ sơ mới tiếp nhé. Hồ sơ đang làm dở
> vẫn sửa và lưu được bình thường.

**Điểm nói — ba câu, không hơn:**

1. Không có chữ "vi phạm" nào, và đó là **ràng buộc kỹ thuật có test giữ**, không
   phải lựa chọn văn phong. Bị phần mềm nói bóng gió là mình gian lận thì người ta
   nhớ rất lâu; bị hỏi một đoạn bối cảnh thì không.
2. Câu từ chối **luôn kèm đường ra**. Một chữ "không" không có bước tiếp theo là
   chỗ người dùng bắt đầu tìm cách đi vòng qua hệ thống.
3. **Hồ sơ đang dở vẫn sửa được.** Bảo người ta "sửa đi" rồi khoá luôn đường sửa
   thì đó là cái bẫy, không phải cơ chế hỗ trợ.

### Cảnh 11 · Mô tả bối cảnh, và người có thẩm quyền gỡ _(Web — hai màn hình)_

**Máy An** — mở một hồ sơ bất kỳ của An. Thẻ hỗ trợ đã nằm sẵn ở đó:

> Hồ sơ gần đây phải chỉnh lại 5 lần trong 30 ngày — cùng xem lại một chút nhé
> · Hay gặp nhất: **Ngân sách chưa khớp**.
> · Giá trị dự toán trên hồ sơ cần khớp với đề nghị mua sắm và đúng đơn vị tiền tệ.
> Sai lệch hay gặp nhất là nhập nhầm đơn vị nghìn/triệu đồng.

Chỉ vào dòng giữa: hệ thống **không** chỉ đếm, nó nói ra **hay sai ở đâu** và mở
đúng trang hướng dẫn cho chỗ đó. Ba trong năm lần trả là cùng một nhóm lý do.

An gõ vào ô đầu (cần tối thiểu 80 ký tự — nút mở khoá khi đủ):

> `Đầu bài từ bộ phận yêu cầu gửi sang thường chỉ có số tiền tạm tính, mình phải tự tra lại PR nên hay lệch đơn vị. Nhờ bên mua sắm cho mẫu đối chiếu trước khi nộp.`

**Máy CHI** — vào **Phê duyệt**. Mục _"Đang chờ hỗ trợ (1)"_ đã hiện. Chi đọc, gõ
phản hồi rồi bấm **Đã trao đổi — gỡ chặn**.

Ba chốt chặn ở phía máy chủ, đáng nói khi Chi bấm:

- Người viết **không tự duyệt được** bản của mình.
- Quyết định **bắt buộc kèm một dòng phản hồi** — im lặng lúc gỡ chặn là thứ làm
  cả cơ chế thành hình phạt.
- Duyệt **đúng một lần**; bấm lại lần hai bị từ chối.

**Máy An** — quay lại Zalo, gõ lại đúng câu ở cảnh 10. Lần này hồ sơ được tạo.

---

## Hai thứ mới trong bản này

### 1 · Câu hỏi luật đi ra web, không đọc kho

Trước: mọi câu hỏi luật đọc corpus đã ingest vào Qdrant. Giờ `domain=legal` đi ra
**chuỗi nhà cung cấp tìm kiếm** (serper → tavily → brave), kho lùi về làm đường lui
cuối. Quy chế nội bộ và hồ sơ nhà thầu vẫn ở Qdrant — chúng không có trên Google.

Ba điểm đáng chỉ vào, nếu có người hỏi sâu:

- **Danh sách nguồn là hàng rào chính, không phải hàng rào phụ.** Kết quả tìm kiếm
  là nội dung không đáng tin — ai cũng SEO được một trang viết "tối thiểu 90 ngày".
  Mọi kết quả ngoài danh sách bị loại **trước khi** nội dung tới model, chứ không
  trông vào việc model tự nhận ra nguồn dởm. Danh sách rỗng = không nhận nguồn nào.
- **Thứ tự nhà cung cấp là cứng, không xoay vòng.** Cùng một câu hỏi phải cho cùng
  một kết quả: khi có người khiếu nại mốc thời gian dự thầu, "đã hỏi máy tìm kiếm
  nào" không nên có đáp án ngẫu nhiên.
- **Đường lui về kho có nói ra.** Tra web không được thì dùng kho, và thẻ CP1 in
  thẳng: _"Căn cứ pháp lý lấy từ kho đã lưu trong hệ thống, không phải tra trực
  tuyến tại thời điểm này — hãy đối chiếu hiệu lực trước khi duyệt."_ Người ký biết
  mình đang ký trên căn cứ loại nào.

Chi tiết: [dw01-hsmt-rag-flow.vi.md §8](../architecture/dw01-hsmt-rag-flow.vi.md).

### 2 · Theo dõi tần suất hồ sơ bị trả lại

Trước: mỗi lần trả hồ sơ là một sự kiện rời rạc, trôi đi cùng thẻ thông báo. Không
ai — kể cả chính người tạo — thấy được là nó đang lặp.

Giờ mỗi lần bị trả được ghi bất biến kèm nhóm nguyên nhân, đếm theo cửa sổ trượt
gom theo người tạo. Hai mức: **nhắc** (3 lần / 7 ngày — hiện thẻ, không cản gì) và
**chặn** (5 lần / 30 ngày — dừng việc mở hồ sơ mới cho tới khi có người ngồi lại).

Nếu bị hỏi _"lỡ hệ thống đếm sai thì sao?"_ — hai câu trả lời đã dựng sẵn:

- **Không đếm được thì không chặn.** Kho dữ liệu lỗi, truy vấn quá hạn — tất cả ra
  "không tính được", và không tính được thì cho đi tiếp. Một cơ chế chặn người dùng
  không được phép chặn vì hạ tầng hỏng.
- **Bấm nhầm gỡ được.** Người duyệt trả nhầm thì đánh dấu lại; bản ghi vẫn còn cho
  kiểm toán nhưng rời khỏi số đếm ngay.

Và số liệu này **không dùng để đánh giá ai** — không xếp hạng, không so sánh giữa
người với người, không gắn định danh người dùng vào bất kỳ chỉ số đo lường nào.

Chi tiết: [docs/specs/dw01-rework-frequency-support/](../specs/dw01-rework-frequency-support/requirements.md).

---

## Nếu còn thời gian

**AN hoặc CHI** — `Điều 20 Luật Đấu thầu quy định gì về bảo lãnh dự thầu?`

**AN** — `tình hình chung thế nào?`

**AN** — `thôi làm nốt cái bàn phím đi` _(chỉ dùng được nếu trước đó có khai dở một
yêu cầu bàn phím)_

---

## Tránh trong lúc quay

- Bot hỏi _"Bạn đang nói về hồ sơ nào?"_ — **đừng gõ `1`**, gõ nguyên câu có tên hồ sơ.
- **Luôn nêu tên hồ sơ.** `gia hạn 10 ngày` một mình là hên xui.
- **Đừng nhắc lại tên hàng khi sửa số.** `à nhầm, 200 thôi` giữ nguyên mô tả; còn
  `à nhầm, 200 màn hình thôi` khiến tiêu đề rút lại thành "Mua màn hình".
- **Đừng hỏi Chi "có đề nghị sửa đổi nào chờ tôi không"** — danh sách đang chờ mới chỉ
  gồm phiếu checkpoint.
- **Phát hiện mua lặp** chưa nối vào luồng (`repeat_purchase.py` có đủ code và test,
  không handler nào gọi). Đừng nhầm nó với cảnh 10–11 — hai cơ chế khác nhau: cái kia
  soi _nội dung gói_, cái này đếm _số lần bị trả_.
- Cảnh **NCC nộp mail → DW02** cần reply email thật, chưa chạy lại trong lần kiểm gần nhất.
- **Đừng chạy `seed_demo_rework.sh` trước cảnh 1.** An sẽ bị chặn ngay câu mở đầu.
- **Đừng quên `demo_reset.sh` giữa các lần quay.** Mỗi lần retake kết thúc bằng một
  hồ sơ bị trả là một dòng cộng vào số đếm; ba lần bỏ dở trong tuần là vừa đúng ngưỡng
  nhắc, và thẻ hỗ trợ sẽ tự hiện ra giữa một cảnh không định nói về nó.
- **Cảnh 11 là cảnh WEB**, không phải Zalo. Chi duyệt bản mô tả bối cảnh trên màn hình
  Phê duyệt — kênh chat chưa hiểu lệnh này.

---

## Teleprompter (tuỳ chọn)

Tự copy từng câu vào clipboard, in điểm nói, tự canh giờ chờ:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1
powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1 -Only chi   # máy thứ hai
powershell -ExecutionPolicy Bypass -File scripts\demo_cue.ps1 -From 9     # sau khi retake
```

Điểm nói từng cảnh nằm ở [demo-lines.yaml](demo-lines.yaml).

Teleprompter phủ **cảnh 1–9** (16 câu Zalo). Cảnh 10–11 có một câu Zalo và phần còn
lại trên web, nên dẫn bằng tay theo mục trên.

---

## Trạng thái kiểm chứng

| Phần                       | Tình trạng                                                          |
| -------------------------- | ------------------------------------------------------------------- |
| Cảnh 1–9, 16 câu Zalo      | Đã chạy liền một mạch trên hồ sơ thật: **16/16**                    |
| Câu trả lời luật đi ra web | Đã đổi nguồn và có test; **chưa quay lại** cả mạch sau khi đổi      |
| Cảnh 10–11                 | Câu chữ và ngưỡng đã kiểm bằng dữ liệu gieo thật; **chưa quay thử** |

Hai dòng dưới cần một lượt chạy thử trước khi quay chính thức. Và cả hai đòi
`make migrate` đã chạy — hai bảng của cảnh 10–11 ra đời ở migration `0015`.
