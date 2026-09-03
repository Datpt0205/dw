# Đối chứng GLM-5.2 (FPT Cloud) vs gpt-5.6-luna (dxrank)

**Ngày đo:** 2026-08-24 · **Stack:** full profile, model thật, DB thật, corpus luật đã nạp
**Người đọc cần biết trước:** đây là số liệu thô kèm hiện tượng quan sát được, không phải
khuyến nghị chọn model. Kết luận để người đọc tự rút.

---

## 1. Cấu hình hai bên

|                     | GLM-5.2                                   | gpt-5.6-luna                             |
| ------------------- | ----------------------------------------- | ---------------------------------------- |
| Profile             | `configs/models/glm.yaml`                 | `configs/models/openai.yaml`             |
| Provider trong code | `fpt_openai`                              | `openai_responses`                       |
| Endpoint            | `https://mkp-api.fptcloud.com/v1`         | `https://portal.dxrank.vn/ai-gateway/v1` |
| Dialect             | `/chat/completions`                       | `/responses`                             |
| Structured output   | `response_format: json_schema` strict     | `text.format` json_schema strict         |
| `reasoning_effort`  | không khai (gateway không phát reasoning) | `low` / `medium` tuỳ route               |

Cả hai chạy **cùng một code path** của kênh Zalo, cùng corpus tri thức (13 điểm Qdrant:
6 chunk Luật Đấu thầu + 4 chunk quy chế nội bộ + 3 tender), cùng `demo_reset.sh` +
`seed_demo_cases.sh` trước mỗi lượt.

---

## 2. Bộ A — harness `scripts/chat_scenarios.py`

Phép kiểm tự động PASS/FAIL, chạy đúng code path kênh Zalo.

| #   | Phép kiểm                                 | GLM-5.2  |   luna    |
| --- | ----------------------------------------- | :------: | :-------: |
| 1   | hồ sơ bàn phím còn nguyên sau khi lan man | **FAIL** |   PASS    |
| 2   | hồ sơ còn nguyên sau khi hỏi luật         | **FAIL** |   PASS    |
| 3   | An không duyệt được (vượt quyền)          |   PASS   |   PASS    |
| 4   | "xác minh" chạy được giữa cuộc trò chuyện |   PASS   |   PASS    |
| 5   | lệnh đi qua decision engine               |   PASS   |   PASS    |
| 6   | "duyệt" trống phải hỏi lại, không tự chọn |   PASS   |   PASS    |
| 7   | chỉ đúng hồ sơ qua tên người đề nghị      |   PASS   |   PASS    |
| 8   | An không thấy hồ sơ của người khác        |   PASS   |   PASS    |
| 9   | không hùa theo tiền đề sai của câu hỏi    |   PASS   |   PASS    |
| 10  | intake một dòng tạo được hồ sơ            | **FAIL** |   PASS    |
|     | **Tổng trên 10 phép kiểm chung**          | **7/10** | **10/10** |

**Lưu ý về phạm vi:** harness có 19 phép kiểm, nhưng nó `return` sớm khi phép kiểm #10
trượt (mọi thứ sau đó phụ thuộc vào hồ sơ được tạo). GLM trượt #10 nên **9 phép kiểm
cuối không chạy**. Lượt luna đi tiếp tới 12/12 rồi bị dừng tay để tiết kiệm thời gian —
**7 phép kiểm cuối không có số liệu cho cả hai bên.**

---

## 3. Bộ B — 16 câu kịch bản demo (`docs/runbooks/demo-lines.yaml`)

Chạy bằng `scripts/replay_demo_lines.py`. Không có assertion — đối chiếu bằng mắt với
cột `note` trong YAML.

### Kết quả tổng

|                                     | GLM-5.2                   | luna      |
| ----------------------------------- | ------------------------- | --------- |
| Số câu đi đúng kịch bản             | **2/16**                  | **16/16** |
| Hồ sơ có được tạo không             | **KHÔNG** (trượt ở câu 4) | Có        |
| Chạy tới CP3 + addendum có hiệu lực | Không                     | Có        |
| Tổng thời gian gọi model            | **81s**                   | 303s      |
| Trung bình mỗi câu                  | **5,1s**                  | 18,9s     |

### Chỗ hỏng gốc — câu 2

Kịch bản: An gõ sai `2000`, rồi sửa `"à nhầm, 200 thôi không phải 2000 nhé"`.
Kỳ vọng: thẻ tóm tắt hiện lại với `200`, **6 trường còn lại giữ nguyên**.

**luna:**

```
Tôi hiểu yêu cầu như sau — bạn xác nhận để tạo hồ sơ nhé?
  • Hàng hoá/dịch vụ: Màn hình cho team AI FDX
  • Số lượng: 200                    ← sửa đúng
  • Ngân sách: 300.000.000.000 VND   ← giữ nguyên
  • Thời hạn: 90 ngày                ← giữ nguyên
  • Giao tại: Kho Hà Nội             ← giữ nguyên
  • NCC dự kiến: Thiết bị Việt, Minh Long, Sao Mai
```

**GLM:**

```
OK, bạn nhắn phần muốn sửa (vd: «ngân sách 1,5 tỷ» hoặc «thêm NCC FPT»)
— mình cập nhật rồi xác nhận lại nhé.
```

GLM không hiểu đây là một phép sửa. Từ đó hồ sơ không bao giờ đầy đủ, câu 4 (`đồng ý`)
không tạo được hồ sơ, và **8 câu cuối đều trả "Hiện không có mục nào như vậy"** vì hồ sơ
không tồn tại. Cùng nguyên nhân với 3 phép kiểm trượt ở Bộ A.

### Chỗ GLM làm tốt — câu 3, đọc luật (RAG)

Câu hỏi: _"gói cỡ này luật bắt cho nhà thầu bao nhiêu ngày chuẩn bị hồ sơ?"_

GLM trả **đúng cả ba mốc**: 18 ngày (rộng rãi trong nước) / 35 ngày (quốc tế) /
05 ngày làm việc (chào hàng cạnh tranh), và **không đoán** khi chưa biết hình thức.

luna trả cùng ba mốc nhưng **kèm trích dẫn nguyên văn hai nguồn** (Luật Đấu thầu và Quy
chế nội bộ, có tên tài liệu và phiên bản `2026-08`) — thứ mà bên duyệt cần để kiểm chứng.

Cả hai đều PASS phép kiểm #9 (không hùa theo tiền đề sai khi được hỏi "Điều 20 quy định
gì về bảo lãnh dự thầu" — Điều 20 nói về chỉ định thầu).

### Lỗi lẫn ký tự ngoại ngữ — chỉ GLM

Hai lần bắt được chữ ngoài tiếng Việt lọt vào câu trả lời gửi cho người dùng:

```
Hiện袋子七个项都没填，thiếu cả món hàng cần mua, số lượng, ngân sách...
```

```
Hiện đang tắc một hồ sơ: اسكان mững: نгуễn Văn An. mua 200 màn hình...
```

Cái thứ hai còn làm hỏng cả tên người (`Nguyễn Văn An` → `نгуễn Văn An`). luna không có
hiện tượng này trong bất kỳ lượt nào.

---

## 4. Tóm tắt hiện tượng

**GLM-5.2 mạnh ở:**

- Tốc độ: nhanh **3,7×** (5,1s vs 18,9s mỗi lượt)
- Đọc và trả lời văn bản luật từ RAG: chính xác, không bịa, không đoán khi thiếu dữ kiện
- Các phép kiểm về phân quyền, phạm vi nhìn, chống tự quyết: PASS toàn bộ

**GLM-5.2 hỏng ở:**

- **Bóc slot và giữ ngữ cảnh** — trượt cả 3 phép kiểm loại này. Đây là khâu toàn bộ luồng
  DW01 dựa vào: không tạo được hồ sơ thì không có gì để duyệt.
- **Lẫn chữ Hán / Ả Rập** vào câu tiếng Việt gửi thẳng cho người dùng.

Lưu ý: các phép kiểm GLM PASS phần lớn là **chặn tất định trong code** (phân quyền, RLS,
decision engine hỏi lại) — chúng PASS gần như bất kể model nào. Ba phép kiểm GLM trượt
đúng là ba phép kiểm phụ thuộc vào chất lượng model.

---

## 5. Cách chạy lại

```bash
DC="docker compose --env-file .env -f infra/compose/docker-compose.yml \
    -f infra/compose/docker-compose.gpu.yml"

# Đổi model: một dòng trong .env, rồi recreate api
#   DW_API_MODEL_PROFILE=glm     (GLM-5.2 qua FPT)
#   DW_API_MODEL_PROFILE=openai  (gpt-5.6-luna qua dxrank)
$DC --profile full up -d --force-recreate api

# Corpus luật (chỉ cần một lần, nếu chưa nạp)
$DC exec -T api python - < scripts/seed_knowledge.py
$DC exec -T api python - < scripts/knowledge_reindex.py

# Trước MỖI lượt đo
bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh

# Bộ A — 19 phép kiểm PASS/FAIL
$DC exec -T api python - < scripts/chat_scenarios.py

# Bộ B — 16 câu kịch bản demo
$DC cp docs/runbooks/demo-lines.yaml api:/tmp/demo-lines.yaml
$DC exec -T api python - < scripts/replay_demo_lines.py
```

Transcript đầy đủ của cả bốn lượt nằm ở thư mục scratchpad của phiên đo:
`glm-chat-scenarios.txt`, `glm-16-lines.txt`, `luna-chat-scenarios.txt`, `luna-16-lines.txt`.

---

## 6. Giới hạn của phép đo này

1. **Mỗi cấu hình chỉ chạy MỘT lượt.** Không có phương sai. Một lượt khác có thể ra khác,
   nhất là với các chỗ model phải quyết định.
2. **7 phép kiểm cuối của Bộ A không có số liệu** cho cả hai bên (xem §2).
3. Bộ B **không có assertion tự động** — đối chiếu bằng mắt với cột `note`.
4. Chưa đo chi phí token/tiền. `budgets` trong hai profile đặt như nhau nhưng chưa đối
   chiếu usage thực tế.
5. Prompt hiện tại (`configs/prompts/conversation/intake_chat@1.12.0.yaml`, chốt ở `conversation/service.py:254`) được viết và
   tinh chỉnh cho luna. **Chưa thử tinh chỉnh prompt riêng cho GLM** — có thể phần bóc
   slot cải thiện được, chưa kiểm chứng.
