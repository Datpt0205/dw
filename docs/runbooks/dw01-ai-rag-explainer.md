# DW01 — LLM & RAG xuất hiện ở đâu, làm gì, giải quyết painpoint nào

Tài liệu giải thích **theo đúng những gì đã triển khai** trong Digital Worker
DW01 (chuẩn bị hồ sơ mời thầu): luồng demo, chỗ AI/LLM tham gia, chỗ RAG tham
gia, mục đích và painpoint nghiệp vụ mà mỗi phần giải quyết.

> Tư tưởng cốt lõi: **Máy làm nhanh phần nặng — con người giữ quyền quyết định.**
> Ba lớp kiểm soát xuyên suốt: **schema validate → RAG grounding → human approval**.

---

## 1. Luồng demo đúng (end-to-end)

| # | Bước | Ai bấm | Máy làm gì | AI/RAG |
| - | ---- | ------ | ---------- | ------ |
| 0 | Nạp tài liệu | **Chi** (admin) | Upload **luật/quy chế** → Docling/OCR → chunk → embed (BGE‑M3) → **index Qdrant** | 📚 RAG (nạp) |
| 1 | Tạo hồ sơ | **An** (chuyên viên) | Nhận **PR đã duyệt** (văn xuôi) | — |
| 2 | **Chuẩn hoá nhu cầu** | *(máy chạy)* | **LLM đọc PR → bóc yêu cầu có cấu trúc + nêu điểm CHƯA RÕ** | 🤖 **LLM** |
| 3 | Báo phê duyệt | *(máy)* | Gửi **Slack DM** cho người phê duyệt | — |
| 4 | Xác minh đầu vào | **Bình** (phê duyệt) | Duyệt intake (người lập không tự duyệt) | — |
| 5 | An bấm **Chạy** | *(máy chạy graph)* | Soạn **phương án mua sắm (CP1)** + **retrieve luật/quy chế làm căn cứ** | 📚 **RAG** |
| 6 | Duyệt **CP1** | **Bình** | Chốt phương án | — |
| 7 | Soạn **HSMT + tiêu chí + shortlist** | *(máy)* | **retrieve luật làm references** cho từng artifact | 📚 **RAG** |
| 8 | **CP2 → CP3 → CP4** | **Bình** | Khoá bản chính thức → phát hành → bàn giao | — |

Xuyên suốt: **Bảng kiểm tuân thủ** (đèn xanh/vàng/đỏ) + **audit** mọi thao tác.

**Phân vai (separation of duties):**
- **An** = chuyên viên: tạo hồ sơ + bấm Chạy. *Không* phê duyệt.
- **Bình** = người phê duyệt: xác minh + duyệt CP1–CP4. *Không* tạo/chạy.
- **Chi** = quản trị: nạp luật dùng chung, xem toàn quyền.
- Cưỡng chế ở backend: *người lập không được tự xác minh hồ sơ của mình*.

---

## 2. LLM (DeepSeek) — ở đâu, làm gì, painpoint

**Xuất hiện tại:** bước **Chuẩn hoá nhu cầu** (`extract_requirements`).

**Làm gì:** đọc **PR viết tự do** → trả về **yêu cầu có cấu trúc** (mã `REQ‑xx`,
nội dung, loại *bắt buộc/tham khảo*) + **tự phát hiện điểm mập mờ** đưa vào danh
sách "cần làm rõ".

Ví dụ thật (chạy live với DeepSeek), từ PR văn xuôi mua 100 laptop:
```
extraction_source: ai
REQ-01 mandatory: Mua 100 máy tính xách tay cho khối vận hành
REQ-02 mandatory: CPU ≥ Intel Core i5 thế hệ mới
REQ-03 mandatory: RAM ≥ 16 GB
REQ-04 mandatory: SSD ≥ 512 GB
REQ-05 mandatory: Màn hình 14" Full HD
REQ-06 mandatory: Giao hàng trong 45 ngày
…(9 yêu cầu)
Cần làm rõ:
  • Số năm bảo hành tối thiểu — CHƯA RÕ
  • Windows bản quyền hay không kèm OS — CHƯA RÕ
  • Địa điểm giao hàng cụ thể — CHƯA RÕ
```

**Painpoint giải quyết:**
- PR mỗi phòng/mỗi người viết **một kiểu, dài dòng** → chuyên viên phải **đọc tay,
  tự liệt kê yêu cầu**, chậm và **dễ sót**.
- Cách cũ (parser cứng) chỉ bắt được **gạch đầu dòng** → PR văn xuôi là "bó tay".
  **LLM hiểu ngữ nghĩa** → chuẩn hoá tự động, đồng nhất định dạng, và **hỏi lại
  đúng chỗ thiếu** thay vì bỏ qua.
- → Rút ngắn khâu bóc nhu cầu từ **hàng giờ xuống vài giây**.

**An toàn:** output LLM luôn được **validate vào schema** (mã, loại, độ dài); nếu
model lỗi/không có key → **fallback** về tách dòng, intake không bao giờ bị chặn.

> Có thể mở rộng LLM sang: soạn nội dung HSMT theo loại gói, sinh tiêu chí đánh
> giá phù hợp, diễn giải căn cứ pháp lý. Hiện đã làm bước **bóc yêu cầu**.

---

## 3. RAG — ở đâu, retrieve gì, mục đích, painpoint

**Xuất hiện tại:** các bước **soạn phương án / HSMT / tiêu chí** (CP1 + build).

**Retrieve gì:** chính các **tài liệu đã upload** — luật đấu thầu (*global*, dùng
chung mọi đơn vị) và quy chế nội bộ (*tenant*, riêng đơn vị) — đã được **chunk +
embed BGE‑M3 + index Qdrant**. Node truy vấn bằng thuật ngữ pháp lý ("hình thức
lựa chọn nhà thầu", "tiêu chí đánh giá"…) → lấy **đoạn liên quan nhất**.

**Mục đích:** gắn làm **căn cứ pháp lý / references** (trích dẫn) vào từng artifact
→ mọi đề xuất **neo vào tài liệu thật, truy vết được về nguồn** — không phải máy
tự bịa.

**Painpoint giải quyết:**
- Đề xuất mua sắm **phải viện dẫn đúng luật/quy chế**; nếu AI "chế" ra → **rủi ro
  pháp lý**. RAG buộc nội dung **có bằng chứng**.
- Mỗi tổ chức có **quy chế riêng** nhưng luật thì **dùng chung** → RAG tách đúng:
  luật *global* mọi đơn vị đọc được, quy chế *tenant* chỉ đơn vị đó thấy (cưỡng
  chế bằng RLS + filter Qdrant — **không rò rỉ chéo tổ chức**).
- → Người duyệt bấm vào xem được **nguồn trích dẫn**, giảm sai sót và tăng niềm tin.

---

## 4. Phân biệt & phối hợp LLM ↔ RAG

| | **LLM** | **RAG** |
| - | ------- | ------- |
| Vai trò | "**Hiểu & viết**" | "**Nhớ & dẫn chứng**" |
| Đầu vào | PR văn xuôi | Kho tài liệu đã nạp |
| Đầu ra | Yêu cầu có cấu trúc | Đoạn luật/quy chế liên quan (citations) |
| Rủi ro nếu thiếu | Phải bóc tay, dễ sót | Đề xuất không có căn cứ, dễ sai luật |

**Phối hợp:** LLM tạo nội dung thích ứng theo từng hồ sơ, RAG bảo đảm nội dung
**dựa trên tài liệu thật** và **trích dẫn được**, cuối cùng **con người duyệt** ở
4 chốt. Máy nhanh — người kiểm soát.

---

## 5. Bốn painpoint nghiệp vụ & cách hệ thống xử lý

| Painpoint (cách làm truyền thống) | Cách DW01 xử lý |
| --------------------------------- | --------------- |
| Bóc nhu cầu từ PR thủ công, chậm, dễ sót | 🤖 **LLM** chuẩn hoá + nêu điểm chưa rõ |
| Soạn hồ sơ phải viện dẫn luật đúng, dễ sai căn cứ | 📚 **RAG** neo vào luật/quy chế đã nạp, trích dẫn được |
| Kiểm tra tuân thủ thủ công, dễ bỏ sót | ✅ **Bảng kiểm tuân thủ** đèn xanh/đỏ tự động |
| Phê duyệt qua email/giấy, chậm, khó truy vết | 🔔 **Slack DM** đúng người + 4 chốt + **audit** |

---

## 6. Câu chốt khi present

> *"PR viết tay lộn xộn → **LLM** chuẩn hoá thành yêu cầu rõ ràng và hỏi lại chỗ
> thiếu. Khi soạn hồ sơ, **RAG** kéo đúng luật/quy chế của đơn vị làm căn cứ để
> không ai 'chế' sai luật. Và **con người vẫn quyết** ở mọi bước quan trọng — máy
> làm nhanh phần nặng, người giữ kiểm soát và truy vết được."*

---

### Cách bật LLM thật (DeepSeek)
`.env`: `DW_MODEL_PROVIDER=openai_compatible`, `OPENAI_BASE_URL=https://api.deepseek.com`,
`OPENAI_API_KEY=sk-...`, `DW_API_MODEL_PROFILE=deepseek`,
`DW_API_OPENAI_STRUCTURED_MODE=json_object` → `docker compose ... up -d api`.
Không có key → tự fallback (parser thô), hệ thống vẫn chạy.
