# DW01 — Theo dõi tần suất hồ sơ bị trả lại và hỗ trợ kịp thời

- **Trạng thái:** Draft
- **Ngày:** 2026-08-26
- **Bối cảnh:** DW01 — bounded context `tender`, slice `preparation`
- **Loại tài liệu:** Đặc tả yêu cầu. **Không phải** thiết kế kỹ thuật — không chốt bảng, không chốt lớp, không chốt endpoint.
- **Tài liệu liên quan:** `docs/architecture/dw01-hsmt-rag-flow.vi.md` (hiện trạng luồng), `docs/overview/DW01_BUSINESS_OVERVIEW.md` §6 "Hàng rào an toàn", `CLAUDE.md` (ràng buộc kiến trúc bắt buộc)

---

## 0. Tóm tắt một đoạn

Khi một người tạo hồ sơ mua sắm bị người duyệt trả lại nhiều lần trong một khoảng thời gian ngắn, hệ thống hiện **không nhớ gì cả** — mỗi lần trả là một sự kiện độc lập, biến mất sau khi thẻ thông báo trôi đi. Tài liệu này đặc tả một cơ chế đếm số lần bị trả lại theo cửa sổ trượt, và khi chạm ngưỡng thì mời người tạo viết một bản giải trình ngắn về bối cảnh, để bộ phận mua sắm hỗ trợ đúng chỗ thay vì để vòng lặp trả–sửa kéo dài.

Đây là tính năng **hỗ trợ**, không phải tính năng kỷ luật. Ràng buộc ngôn từ ở §7.10 là bắt buộc, không phải khuyến nghị.

---

## 1. Vấn đề nghiệp vụ

### 1.1 Hiện trạng

| Điều đang xảy ra                                                                     | Bằng chứng trong code                                                                                                                                         |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hồ sơ bị trả lại ở 3 chốt khác nhau, mỗi chốt một trạng thái riêng                   | `CaseState.INTAKE_REJECTED` / `CP1_REJECTED` / `CP2_REJECTED` — `packages/python/dw_tender/src/dw_tender/domain/preparation/entities.py:27,33,38`             |
| Gate tự động không đạt chỉ hiện lên một thẻ thông báo phù du gửi người tạo, rồi thôi | `_notify_progress(...)` trong `packages/python/dw_tender/src/dw_tender/workflows/preparation_v1/nodes.py`, thẻ `⚠️ Gate CP1 CHƯA ĐẠT — cần bổ sung`           |
| Chỉ một trong ba chốt có audit action                                                | `preparation.intake.rejected` được ghi trong `packages/python/dw_tender/src/dw_tender/presentation/preparation_api.py`; không có action tương ứng cho CP1/CP2 |
| Không có bất kỳ bộ đếm nào theo người dùng hay theo thời gian                        | Toàn repo không có bảng, cột, hay lớp nào cho việc này                                                                                                        |
| Không truy vấn được lịch sử hồ sơ theo người tạo                                     | `PreparationCaseRepositoryPort` chỉ có `list_recent(limit)` — `packages/python/dw_tender/src/dw_tender/application/preparation/ports.py:41`                   |

### 1.2 Hệ quả

- Người tạo hồ sơ lặp lại **cùng một loại thiếu sót** mà không ai chỉ ra rằng nó đang lặp.
- Người duyệt trả đi trả lại, tốn thời gian cho việc lẽ ra chỉ cần hướng dẫn một lần.
- Trưởng bộ phận mua sắm **không có dữ liệu** để biết ai đang cần hỗ trợ, cần hỗ trợ về cái gì.
- Vòng lặp trả–sửa kéo dài âm thầm, chỉ lộ ra khi lỡ hạn gói thầu.

### 1.3 Kết quả mong muốn

Phát hiện sớm mẫu lặp lại → mời người tạo mô tả bối cảnh → định tuyến hỗ trợ đúng người, đúng việc, **trước khi** nó thành sự cố tiến độ.

### 1.4 Tiền lệ đã có trong repo

Cơ chế "cửa sổ trượt + ngưỡng + ép viết giải trình" **đã tồn tại và đã được test** ở `packages/python/dw_tender/src/dw_tender/application/preparation/repeat_purchase.py` — hàm thuần `find_repeat(...)` và `RepeatFinding.as_clarification()` sinh ra một mục clarification `blocking=True`. Nhưng nó **chưa được nối vào bất kỳ node hay handler nào**: hiện chỉ có unit test gọi tới.

Đặc tả này đi theo đúng khuôn mẫu đó — cùng triết lý ngưỡng-đặt-trong-config, cùng chuẩn ngôn từ, cùng cách ép giải trình bằng mục blocking.

---

## 2. Phạm vi

### 2.1 Trong phạm vi

- Ghi nhận bất biến mỗi lần một hồ sơ bị **người duyệt** trả lại, ở cả ba chốt (intake, CP1, CP2).
- Đếm số lần bị trả lại theo **cửa sổ trượt**, gom theo **người tạo hồ sơ** trong phạm vi một workspace.
- Hai mức ngưỡng: **ngưỡng nhắc** (chặn mềm) và **ngưỡng chặn** (chặn cứng).
- Bản giải trình: người tạo nhập, hệ thống lưu bất biến, gắn với hồ sơ và với các lần bị trả lại đã tính.
- Duyệt bản giải trình để gỡ chặn cứng, có phân tách trách nhiệm.
- Thông báo tới người tạo và tới người hỗ trợ, qua đúng hạ tầng thông báo hiện có.
- Ngưỡng và độ dài cửa sổ đặt trong quy chế cấu hình được.

### 2.2 Ngoài phạm vi

| Ngoài phạm vi                                                                         | Lý do                                                                                                                                                   |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Đếm gate tự động không đạt (`approach_gate` / `solicitation_gate` trả `passed=False`) | Gate là công cụ soạn thảo, không đạt là chuyện bình thường giữa chừng. Đếm nó sẽ phạt người dùng vì đã dùng công cụ đúng cách. Có thể xem xét ở bản sau |
| Đếm từng `Finding` mức `blocker` trong `ReadinessReport`                              | Cùng lý do; thêm nữa một hồ sơ có thể sinh nhiều blocker cùng lúc, làm số đếm phồng lên vô nghĩa                                                        |
| Chấm điểm, xếp hạng, hoặc so sánh giữa các nhân sự                                    | Trái mục tiêu hỗ trợ; và tạo áp lực khiến người dùng né hệ thống                                                                                        |
| Dùng số liệu này cho đánh giá KPI hay chế tài lao động                                | Không phải mục đích thu thập. Cần đưa vào diện cấm rõ ràng                                                                                              |
| Mở rộng sang bounded context `work_ops`                                               | `CLAUDE.md` yêu cầu hai context độc lập; mở rộng cần một đặc tả riêng                                                                                   |
| Tự động sinh nội dung giải trình bằng LLM                                             | Bản giải trình phải là lời của con người thì mới có giá trị hỗ trợ                                                                                      |

---

## 3. Thuật ngữ

| Thuật ngữ          | Định nghĩa                                                                                                                                                                |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Lần trả lại**    | Một sự kiện trong đó người duyệt chủ động trả hồ sơ về cho người tạo ở một chốt (intake / CP1 / CP2), kèm lý do bắt buộc. Đây là **đơn vị đếm duy nhất** của tài liệu này |
| **Cửa sổ trượt**   | Khoảng thời gian tính ngược từ thời điểm hiện tại (ví dụ "7 ngày gần nhất"), **không** phải tuần lịch hay tháng lịch                                                      |
| **Ngưỡng nhắc**    | Số lần trả lại trong cửa sổ nhắc, đạt tới thì kích hoạt chặn mềm                                                                                                          |
| **Ngưỡng chặn**    | Số lần trả lại trong cửa sổ chặn, đạt tới thì kích hoạt chặn cứng                                                                                                         |
| **Chặn mềm**       | Hiển thị thẻ hỗ trợ và mở form giải trình, nhưng **vẫn cho người tạo tiếp tục làm việc bình thường**                                                                      |
| **Chặn cứng**      | Từ chối tạo hồ sơ mới và từ chối trình duyệt, cho tới khi bản giải trình được duyệt                                                                                       |
| **Bản giải trình** | Bản ghi văn bản do người tạo nhập, mô tả bối cảnh và khó khăn. Bất biến sau khi nộp                                                                                       |
| **Người hỗ trợ**   | Người nhận thông báo và duyệt bản giải trình. Xác định theo vai trò cấu hình trong quy chế                                                                                |
| **Quy chế**        | Tập tin cấu hình chứa ngưỡng và cửa sổ, thuộc `configs/policies/dw01/`, có `policy_version`                                                                               |

> **Lưu ý về từ ngữ.** Tài liệu này cố ý **không** dùng từ "vi phạm" làm thuật ngữ nghiệp vụ. Xem §7.11.

---

## 4. Nhân vật

Vai trò bám theo role key có thật trong `scripts/seed_demo.py` và `configs/demo/demo_users.yaml`.

| Nhân vật               | Role key                                 | Quan tâm gì                                                            |
| ---------------------- | ---------------------------------------- | ---------------------------------------------------------------------- |
| Người tạo hồ sơ        | `member`                                 | Biết mình đang lặp lại điều gì; được hỗ trợ thay vì bị trả tiếp        |
| Người duyệt            | `approver`                               | Ghi được lý do trả lại một cách có cấu trúc, không phải gõ lại mỗi lần |
| Trưởng bộ phận mua sắm | `procurement_head`                       | Thấy ai cần hỗ trợ, cần hỗ trợ cái gì; duyệt bản giải trình            |
| Quản trị nền tảng      | `platform_admin`                         | Nhận leo thang khi bản giải trình bị treo                              |
| Quản trị quy chế       | `procurement_head` hoặc `platform_admin` | Chỉnh ngưỡng và cửa sổ mà không phải nhờ dev                           |

---

## 5. Giả định và phụ thuộc

Các khoảng trống kỹ thuật dưới đây là **điều kiện cần** — không có chúng thì đặc tả này không thực thi được. Liệt kê ở đây để phiên thiết kế không bỏ sót.

**5.1 Domain chưa mang mốc thời gian.** `PreparationCase` không có `created_at` hay `updated_at` ở tầng domain — chúng chỉ tồn tại trên bảng `tender.preparation_cases`. Mọi phép đếm theo cửa sổ trượt sẽ cần một read model hoặc một bản ghi sự kiện riêng có mốc thời gian.

**5.2 Chưa có truy vấn theo người tạo.** `PreparationCaseRepositoryPort` (`.../application/preparation/ports.py:20-41`) chỉ có `list_recent(limit)`. Cần một cổng đọc mới.

**5.3 Chỉ một trong ba chốt có audit action.** Hiện chỉ có `preparation.intake.rejected`. CP1/CP2 bị trả lại không để lại dấu vết audit nào.

**5.4 Thông báo cần loại sự kiện mới.** `IntakeNotificationType` (`.../domain/preparation/notifications.py:15-35`) chưa có loại nào phù hợp. Và `_reply_hint(...)` trong `packages/python/dw_connectors/src/dw_connectors/adapters/zalo_approval_notifier.py` **trả chuỗi rỗng cho event type lạ** — thêm loại mới mà quên thêm nhánh thì thẻ Zalo sẽ không có lời gọi hành động nào.

**5.5 Nợ kỹ thuật về release manifest.** `scripts/release_manifest.py::_policies()` chỉ quét `configs/policies/*.yaml` ở cấp cao nhất, nên rule pack `configs/policies/dw01/procurement_rules_v1.yaml` **hiện không nằm trong release manifest** dù nó điều khiển mọi gate. Nếu ngưỡng của tính năng này đặt trong thư mục lồng, nợ đó phải được trả — nếu không, `policy_version` sẽ không truy vết được về run.

**5.6 Ràng buộc kiến trúc kế thừa.** Theo `CLAUDE.md` và `[tool.importlinter]` trong `pyproject.toml`: `dw_tender` không được phụ thuộc `dw_work_ops`; `domain` không được import FastAPI/SQLAlchemy/LangGraph; chỉ composition root mới import adapter cụ thể.

**5.7 Nền tảng UI đã sẵn.** Cơ chế "phải nhập văn bản mới đi tiếp được" đã tồn tại: form clarification tại `apps/web/app/procurement/dw01/cases/[caseId]/page.tsx` khoá nút nộp khi còn mục `blocking` chưa trả lời. Bản giải trình nên tái dùng khuôn này thay vì dựng mới.

---

## 6. User stories và acceptance criteria

### US-1 — Ghi nhận mỗi lần hồ sơ bị trả lại

> **Là một** hệ thống,
> **tôi muốn** ghi lại một cách bất biến mỗi lần hồ sơ bị người duyệt trả về,
> **để** có dữ liệu tin cậy làm cơ sở cho mọi phép đếm về sau.

**Acceptance criteria**

- [ ] Trả lại ở cả ba chốt (intake, CP1, CP2) đều sinh một bản ghi, không chốt nào bị bỏ sót.
- [ ] Bản ghi mang đủ: tenant, workspace, hồ sơ, người tạo hồ sơ, người trả, chốt, lý do, nhóm nguyên nhân, thời điểm có múi giờ.
- [ ] Lý do rỗng thì thao tác trả lại bị từ chối; không sinh bản ghi nửa vời.
- [ ] Bản ghi không sửa được, không xoá được sau khi đã ghi.
- [ ] Ghi bản ghi và đổi trạng thái hồ sơ nằm trong **cùng một giao dịch** — không có trường hợp hồ sơ bị trả mà không có bản ghi, hoặc ngược lại.

_Truy vết: RF-01, RF-02, RF-03, RF-04, RF-05, RF-06, RF-07, RF-08_

---

### US-2 — Người tạo tự thấy tần suất của mình

> **Là một** người tạo hồ sơ,
> **tôi muốn** thấy hồ sơ của mình đã bị trả bao nhiêu lần gần đây và vì nhóm lý do gì,
> **để** tôi tự sửa trước khi nộp tiếp, không phải chờ bị trả thêm lần nữa.

**Acceptance criteria**

- [ ] Trang hồ sơ hiển thị số lần bị trả trong cửa sổ nhắc và trong cửa sổ chặn.
- [ ] Hiển thị nhóm nguyên nhân xuất hiện nhiều nhất, kèm lý do gần nhất của người duyệt.
- [ ] Người tạo luôn thấy được số liệu **của chính mình**, kể cả khi chưa chạm ngưỡng nào.
- [ ] Số liệu tất định: cùng dữ liệu và cùng mốc thời gian thì cùng kết quả.

_Truy vết: RF-10, RF-11, RF-12, RF-13, RF-14, RF-15, RF-16, RF-90, RF-92_

---

### US-3 — Chặn mềm khi chạm ngưỡng nhắc

> **Là một** người tạo hồ sơ,
> **tôi muốn** được nhắc và được mời mô tả khó khăn khi số lần bị trả bắt đầu nhiều,
> **để** tôi nhận hỗ trợ sớm mà công việc vẫn chạy.

**Acceptance criteria**

- [ ] Chạm ngưỡng nhắc thì thẻ hỗ trợ xuất hiện và form giải trình mở ra.
- [ ] Người tạo **vẫn nộp được** hồ sơ và **vẫn tạo được** hồ sơ mới.
- [ ] Thẻ nêu số lần, cửa sổ, nhóm nguyên nhân chính, và một gợi ý hỗ trợ cụ thể.
- [ ] Thẻ không chứa bất kỳ từ quy kết nào (§7.11).
- [ ] Thẻ hiện đúng một lần cho mỗi lần chạm ngưỡng, không lặp lại ở mỗi lần tải trang.

_Truy vết: RF-30, RF-31, RF-32, RF-33, RF-34, RF-35, RF-36, RF-91_

---

### US-4 — Chặn cứng khi chạm ngưỡng chặn

> **Là một** trưởng bộ phận mua sắm,
> **tôi muốn** hệ thống tạm dừng việc nộp hồ sơ mới khi số lần bị trả đã ở mức phải ngồi lại với nhau,
> **để** chúng tôi xử lý gốc rễ thay vì để hồ sơ lỗi tiếp tục vào hàng đợi.

**Acceptance criteria**

- [ ] Chạm ngưỡng chặn thì mọi yêu cầu tạo hồ sơ mới và trình duyệt bị từ chối, kèm mã lỗi và hướng dẫn gỡ chặn.
- [ ] Hồ sơ đang dở **vẫn sửa được, vẫn lưu được** — chỉ chặn việc trình lên và việc mở hồ sơ mới.
- [ ] Cả hai ngưỡng cùng chạm thì áp dụng chặn cứng.
- [ ] Chặn cứng chỉ gỡ bằng việc duyệt bản giải trình, không tự hết hạn theo thời gian.
- [ ] Không tính được tần suất vì lỗi hạ tầng thì **không chặn** (fail-open), và ghi cảnh báo vận hành.

_Truy vết: RF-40, RF-41, RF-42, RF-43, RF-44, RF-45, RF-46, RF-47, RF-98_

---

### US-5 — Người hỗ trợ nhận được ngữ cảnh, không phải bản cáo trạng

> **Là một** trưởng bộ phận mua sắm,
> **tôi muốn** nhận thông báo kèm đủ ngữ cảnh khi ai đó chạm ngưỡng,
> **để** tôi liên hệ hỗ trợ đúng vấn đề.

**Acceptance criteria**

- [ ] Chạm ngưỡng chặn thì người hỗ trợ nhận thông báo, xác định theo vai trò trong quy chế.
- [ ] Thông báo nêu số lần, cửa sổ, nhóm nguyên nhân chính, và liên kết tới bản giải trình.
- [ ] Thông báo có khoá chống trùng — chạm ngưỡng nhiều lần không sinh nhiều thẻ trùng nhau.
- [ ] Bản giải trình treo quá hạn cấu hình thì leo thang lên `platform_admin`.
- [ ] Thẻ trên kênh chat có lời gọi hành động rõ ràng, không rơi vào nhánh mặc định rỗng.

_Truy vết: RF-70, RF-71, RF-72, RF-73, RF-74, RF-75, RF-76_

---

### US-6 — Quản trị quy chế chỉnh ngưỡng không cần dev

> **Là một** quản trị quy chế,
> **tôi muốn** chỉnh ngưỡng và độ dài cửa sổ trong tập tin quy chế,
> **để** hiệu chỉnh theo thực tế mà không phải chờ một đợt phát hành.

**Acceptance criteria**

- [ ] Ngưỡng và cửa sổ nằm trong quy chế, không hard-code trong Python.
- [ ] Quy chế thiếu trường hoặc sai kiểu thì hệ thống từ chối khởi động với thông báo rõ tập tin nào.
- [ ] Đặt ngưỡng bằng 0 hoặc bỏ trống thì tính năng tắt hoàn toàn, không cảnh báo, không chặn.
- [ ] Đổi ngưỡng phải kèm tăng `policy_version`, và version đó truy vết được về từng lần chặn.

_Truy vết: RF-20, RF-21, RF-22, RF-23, RF-24, RF-25_

---

### US-7 — Bản giải trình được lưu bất biến và tra cứu được

> **Là một** kiểm toán viên nội bộ,
> **tôi muốn** tra được ai đã giải trình gì, ai đã duyệt, vào lúc nào,
> **để** quyết định gỡ chặn có bằng chứng.

**Acceptance criteria**

- [ ] Bản giải trình lưu nguyên văn, không sửa được sau khi nộp.
- [ ] Bản giải trình gắn với danh sách các lần trả lại đã được tính vào ngưỡng tại thời điểm nộp.
- [ ] Nộp, duyệt, từ chối đều sinh sự kiện audit riêng.
- [ ] Quyết định duyệt bắt buộc kèm nhận xét không rỗng.
- [ ] Bản giải trình chỉ đọc được bởi chính người nộp và các vai trò được cấu hình.

_Truy vết: RF-50, RF-51, RF-52, RF-53, RF-54, RF-55, RF-56, RF-57, RF-60, RF-61, RF-62, RF-63, RF-64, RF-65, RF-66, RF-80, RF-93_

---

### US-8 — Gợi ý hỗ trợ theo nhóm nguyên nhân

> **Là một** người tạo hồ sơ,
> **tôi muốn** được chỉ đúng chỗ mình hay sai, kèm hướng dẫn cụ thể,
> **để** lần sau không lặp lại.

**Acceptance criteria**

- [ ] Hệ thống xác định nhóm nguyên nhân xuất hiện nhiều nhất trong cửa sổ.
- [ ] Mỗi nhóm nguyên nhân có một gợi ý hỗ trợ tương ứng, lấy từ quy chế.
- [ ] Nhóm nguyên nhân không có gợi ý thì hiển thị hướng dẫn chung, không hiển thị chỗ trống.
- [ ] Số lần bằng nhau giữa nhiều nhóm thì chọn theo thứ tự tất định, không ngẫu nhiên.

_Truy vết: RF-02, RF-33, RF-34, RF-35_

---

## 7. Yêu cầu theo EARS

### 7.1 Quy ước ký hiệu

Dùng năm mẫu EARS chuẩn. Từ khoá `WHEN` / `IF` / `THEN` / `WHILE` / `WHERE` / `SHALL` / `SHALL NOT` giữ nguyên tiếng Anh để không mất tính đơn nghĩa; phần còn lại viết tiếng Việt. Chủ thể luôn là **Hệ thống**.

| Mẫu          | Dạng                                              | Dùng cho                             |
| ------------ | ------------------------------------------------- | ------------------------------------ |
| Ubiquitous   | Hệ thống SHALL ⟨hành vi⟩                          | Hành vi luôn đúng                    |
| Event-driven | WHEN ⟨sự kiện⟩, Hệ thống SHALL ⟨hành vi⟩          | Phản ứng với một sự kiện             |
| State-driven | WHILE ⟨trạng thái⟩, Hệ thống SHALL ⟨hành vi⟩      | Hành vi duy trì trong một trạng thái |
| Unwanted     | IF ⟨điều kiện xấu⟩, THEN Hệ thống SHALL ⟨hành vi⟩ | Xử lý lỗi, lạm dụng, biên            |
| Optional     | WHERE ⟨tính năng bật⟩, Hệ thống SHALL ⟨hành vi⟩   | Hành vi phụ thuộc cấu hình           |

**Về mã định danh.** Dùng tiền tố `RF-` (rework frequency), **không dùng `REQ-`**. Lý do: `REQ-NN` đã là dữ liệu nghiệp vụ có thật trong hệ thống — `ExtractedRequirement.code` ràng buộc `pattern=^REQ-\d{2}$` (`.../application/preparation/extraction.py`), là các yêu cầu kỹ thuật LLM bóc ra từ đề nghị mua sắm. Trùng tiền tố sẽ gây nhầm lẫn khi tìm kiếm.

---

### 7.2 Ghi nhận lần trả lại

**RF-01** — WHEN người duyệt trả lại một hồ sơ ở bất kỳ chốt nào trong `intake`, `CP1`, `CP2`, Hệ thống SHALL ghi một bản ghi lần trả lại gồm: `tenant_id`, `workspace_id`, định danh hồ sơ, định danh người tạo hồ sơ, định danh người trả lại, chốt, nhóm nguyên nhân, lý do nguyên văn, và thời điểm có múi giờ.

**RF-02** — Hệ thống SHALL yêu cầu người duyệt chọn một **nhóm nguyên nhân** từ danh mục đóng được định nghĩa trong quy chế khi thực hiện thao tác trả lại.

**RF-03** — Hệ thống SHALL lưu lý do nguyên văn do người duyệt nhập, tách biệt với nhóm nguyên nhân, không cắt xén và không diễn giải lại.

**RF-04** — IF lý do trả lại rỗng hoặc chỉ chứa khoảng trắng, THEN Hệ thống SHALL từ chối thao tác trả lại và SHALL NOT ghi bản ghi lần trả lại.

**RF-05** — IF nhóm nguyên nhân không thuộc danh mục trong quy chế, THEN Hệ thống SHALL từ chối thao tác trả lại.

**RF-06** — Hệ thống SHALL ghi bản ghi lần trả lại và cập nhật trạng thái hồ sơ trong cùng một giao dịch, sao cho không tồn tại trạng thái mà một trong hai có còn một cái không.

**RF-07** — Hệ thống SHALL NOT cho phép sửa hoặc xoá một bản ghi lần trả lại sau khi đã ghi.

**RF-08** — WHEN một lần trả lại được ghi, Hệ thống SHALL phát một sự kiện audit riêng cho chốt tương ứng, đủ để dựng lại toàn bộ lịch sử trả lại của một hồ sơ từ nhật ký audit.

---

### 7.3 Đếm theo cửa sổ trượt

**RF-10** — Hệ thống SHALL đếm số lần trả lại gom theo **người tạo hồ sơ**, trong phạm vi một `workspace_id`.

**RF-11** — Hệ thống SHALL đếm theo cửa sổ trượt tính ngược từ thời điểm hiện tại, SHALL NOT đếm theo tuần lịch hoặc tháng lịch.

**RF-12** — Hệ thống SHALL duy trì **hai cửa sổ độc lập**: một cửa sổ nhắc và một cửa sổ chặn, mỗi cửa sổ có độ dài và ngưỡng riêng.

**RF-13** — WHEN cùng một hồ sơ bị trả lại nhiều lần, Hệ thống SHALL đếm mỗi lần trả lại là một sự kiện riêng biệt.

**RF-14** — Hệ thống SHALL NOT cộng gộp số lần trả lại giữa các `workspace_id` khác nhau, kể cả khi cùng một người dùng.

**RF-15** — Hệ thống SHALL cho ra cùng một kết quả đếm khi được gọi lại với cùng tập bản ghi và cùng mốc thời gian tham chiếu.

**RF-16** — WHEN một hồ sơ bị xoá hoặc bị ẩn, Hệ thống SHALL giữ nguyên các bản ghi lần trả lại của hồ sơ đó trong phép đếm.

---

### 7.4 Ngưỡng và cấu hình

**RF-20** — Hệ thống SHALL đọc độ dài cửa sổ nhắc, ngưỡng nhắc, độ dài cửa sổ chặn, ngưỡng chặn, danh mục nhóm nguyên nhân, gợi ý hỗ trợ theo nhóm, vai trò người hỗ trợ, và hạn leo thang, từ một tập tin quy chế trong `configs/policies/dw01/`.

**RF-21** — Hệ thống SHALL NOT chứa giá trị ngưỡng hoặc độ dài cửa sổ dưới dạng hằng số trong mã nguồn Python.

**RF-22** — Giá trị mặc định đề xuất: cửa sổ nhắc **7 ngày** / ngưỡng nhắc **3 lần**; cửa sổ chặn **30 ngày** / ngưỡng chặn **5 lần**; hạn leo thang **48 giờ**. Hệ thống SHALL coi đây là giá trị khởi điểm cần hiệu chỉnh theo số liệu thực tế, không phải hằng số nghiệp vụ.

**RF-23** — IF quy chế thiếu trường bắt buộc hoặc có kiểu dữ liệu sai, THEN Hệ thống SHALL từ chối khởi động và SHALL nêu rõ đường dẫn tập tin quy chế trong thông báo lỗi.

**RF-24** — WHERE ngưỡng nhắc và ngưỡng chặn đều được đặt bằng 0 hoặc bỏ trống, Hệ thống SHALL vô hiệu hoá toàn bộ tính năng này, SHALL NOT hiển thị thẻ hỗ trợ và SHALL NOT chặn bất kỳ thao tác nào.

**RF-25** — WHEN Hệ thống áp dụng chặn mềm hoặc chặn cứng, Hệ thống SHALL ghi kèm `policy_version` của quy chế đã dùng, sao cho một quyết định chặn trong quá khứ truy vết được về đúng bộ ngưỡng khi đó.

---

### 7.5 Chặn mềm — ngưỡng nhắc

**RF-30** — WHEN số lần trả lại của một người tạo trong cửa sổ nhắc đạt tới ngưỡng nhắc, Hệ thống SHALL kích hoạt trạng thái chặn mềm cho người đó.

**RF-31** — WHILE một người tạo đang ở trạng thái chặn mềm và chưa chạm ngưỡng chặn, Hệ thống SHALL hiển thị thẻ hỗ trợ trên trang hồ sơ và SHALL cho phép người đó tiếp tục tạo hồ sơ và trình duyệt bình thường.

**RF-32** — WHILE một người tạo đang ở trạng thái chặn mềm, Hệ thống SHALL mở form giải trình ở dạng tuỳ chọn, không bắt buộc hoàn thành trước khi thao tác tiếp.

**RF-33** — Thẻ hỗ trợ SHALL nêu: số lần trả lại, độ dài cửa sổ, nhóm nguyên nhân xuất hiện nhiều nhất, và gợi ý hỗ trợ tương ứng lấy từ quy chế.

**RF-34** — IF nhóm nguyên nhân xuất hiện nhiều nhất không có gợi ý hỗ trợ trong quy chế, THEN Hệ thống SHALL hiển thị hướng dẫn chung được cấu hình sẵn, SHALL NOT hiển thị vùng nội dung trống.

**RF-35** — IF nhiều nhóm nguyên nhân có cùng số lần xuất hiện cao nhất, THEN Hệ thống SHALL chọn nhóm theo thứ tự khai báo trong quy chế, SHALL NOT chọn ngẫu nhiên.

**RF-36** — Hệ thống SHALL hiển thị thẻ hỗ trợ đúng một lần cho mỗi lần chuyển vào trạng thái chặn mềm, SHALL NOT hiển thị lại ở mỗi lần tải trang sau khi người tạo đã ghi nhận thẻ.

---

### 7.6 Chặn cứng — ngưỡng chặn

**RF-40** — WHEN số lần trả lại của một người tạo trong cửa sổ chặn đạt tới ngưỡng chặn, Hệ thống SHALL kích hoạt trạng thái chặn cứng cho người đó trong `workspace_id` tương ứng.

**RF-41** — WHILE một người tạo đang ở trạng thái chặn cứng, Hệ thống SHALL từ chối mọi yêu cầu tạo hồ sơ mới và mọi yêu cầu chuyển hồ sơ sang trạng thái chờ duyệt, kèm mã lỗi và thông điệp nêu rõ cách gỡ chặn.

**RF-42** — WHILE một người tạo đang ở trạng thái chặn cứng, Hệ thống SHALL vẫn cho phép người đó xem, sửa và lưu các hồ sơ đang dở.

**RF-43** — WHILE một người tạo đang ở trạng thái chặn cứng, Hệ thống SHALL yêu cầu bản giải trình như một mục bắt buộc, theo đúng cơ chế mục `blocking` đang dùng cho danh sách làm rõ.

**RF-44** — IF cả ngưỡng nhắc và ngưỡng chặn cùng bị chạm, THEN Hệ thống SHALL áp dụng chặn cứng.

**RF-45** — Hệ thống SHALL NOT tự động gỡ chặn cứng khi số lần trả lại rơi xuống dưới ngưỡng do các bản ghi cũ trôi ra khỏi cửa sổ; chặn cứng chỉ gỡ theo §7.8.

**RF-46** — Hệ thống SHALL NOT chặn người tạo dựa trên hồ sơ do người khác tạo, kể cả khi hồ sơ đó được nộp thay mặt người tạo.

**RF-47** — Hệ thống SHALL chặn ở tầng máy chủ và SHALL NOT dựa vào việc ẩn nút trên giao diện như một biện pháp phân quyền.

---

### 7.7 Bản giải trình

**RF-50** — Hệ thống SHALL cho phép người tạo nộp một bản giải trình gồm phần mô tả bối cảnh, phần nêu khó khăn, và phần đề xuất hỗ trợ mong muốn.

**RF-51** — IF nội dung bản giải trình rỗng hoặc ngắn hơn độ dài tối thiểu trong quy chế, THEN Hệ thống SHALL từ chối việc nộp.

**RF-52** — WHEN một bản giải trình được nộp, Hệ thống SHALL gắn vào bản ghi đó danh sách định danh của các lần trả lại đã được tính vào ngưỡng tại đúng thời điểm nộp.

**RF-53** — Hệ thống SHALL NOT cho phép sửa hoặc xoá nội dung bản giải trình sau khi đã nộp.

**RF-54** — WHERE người tạo cần bổ sung thông tin sau khi đã nộp, Hệ thống SHALL cho phép nộp một bản giải trình mới nối tiếp, SHALL NOT ghi đè bản cũ.

**RF-55** — Hệ thống SHALL ghi một sự kiện audit khi bản giải trình được nộp, gồm người nộp, thời điểm, và hồ sơ liên quan.

**RF-56** — Hệ thống SHALL NOT sinh nội dung bản giải trình bằng mô hình ngôn ngữ, và SHALL NOT điền sẵn nội dung gợi ý vào ô nhập.

**RF-57** — Hệ thống SHALL lưu bản giải trình trong phạm vi `tenant_id` và `workspace_id` của hồ sơ liên quan.

---

### 7.8 Duyệt bản giải trình và gỡ chặn

**RF-60** — WHEN một bản giải trình được nộp trong trạng thái chặn cứng, Hệ thống SHALL tạo một yêu cầu duyệt gửi tới vai trò người hỗ trợ được cấu hình trong quy chế.

**RF-61** — Hệ thống SHALL từ chối quyết định duyệt nếu vai trò yêu cầu không nằm trong tập vai trò của người thực hiện, theo đúng cơ chế `required_role` đang dùng ở `ApproveAndResumeService.decide` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py`).

**RF-62** — WHEN người có thẩm quyền duyệt một bản giải trình, Hệ thống SHALL gỡ trạng thái chặn cứng của người tạo và SHALL ghi một sự kiện audit gồm người duyệt, thời điểm, và nhận xét.

**RF-63** — IF nhận xét của người duyệt rỗng hoặc chỉ chứa khoảng trắng, THEN Hệ thống SHALL từ chối quyết định duyệt.

**RF-64** — IF người thực hiện quyết định duyệt chính là người đã nộp bản giải trình đó, THEN Hệ thống SHALL từ chối quyết định duyệt.

**RF-65** — WHEN một bản giải trình bị từ chối, Hệ thống SHALL giữ nguyên trạng thái chặn cứng và SHALL thông báo lý do từ chối cho người tạo.

**RF-66** — IF một bản giải trình đã có quyết định, THEN Hệ thống SHALL từ chối mọi quyết định tiếp theo trên chính bản đó.

---

### 7.9 Thông báo và leo thang

**RF-70** — WHEN một người tạo chuyển sang trạng thái chặn cứng, Hệ thống SHALL gửi thông báo tới người hỗ trợ được xác định theo vai trò trong quy chế.

**RF-71** — Thông báo SHALL nêu: số lần trả lại, độ dài cửa sổ, nhóm nguyên nhân xuất hiện nhiều nhất, và đường dẫn tới bản giải trình.

**RF-72** — Hệ thống SHALL gắn khoá chống trùng cho mỗi thông báo theo khuôn `dw01:{case_id}:{event}:{dedupe}` đang dùng trong slice này, sao cho việc chạm ngưỡng nhiều lần không sinh nhiều thông báo trùng nội dung.

**RF-73** — IF một bản giải trình chưa có quyết định sau hạn leo thang trong quy chế, THEN Hệ thống SHALL gửi thông báo leo thang tới `platform_admin`.

**RF-74** — Hệ thống SHALL loại người tạo hồ sơ ra khỏi danh sách người nhận thông báo dành cho người hỗ trợ, theo đúng cơ chế `find_recipient_for_role(role_key, exclude=...)` đang có.

**RF-75** — WHERE thông báo được gửi qua kênh chat, Hệ thống SHALL kèm một lời gọi hành động tường minh cho loại sự kiện mới, SHALL NOT rơi vào nhánh mặc định trả về nội dung rỗng.

**RF-76** — IF việc gửi thông báo thất bại, THEN Hệ thống SHALL thử lại theo cơ chế hàng đợi bền hiện có và SHALL NOT làm hỏng giao dịch nghiệp vụ đã cam kết.

---

### 7.10 Đa tenant, phân quyền và audit

**RF-80** — Hệ thống SHALL giới hạn mọi truy vấn bản ghi lần trả lại và bản giải trình trong phạm vi `tenant_id` và `workspace_id` của ngữ cảnh truy cập đã được máy chủ xác thực.

**RF-81** — Hệ thống SHALL NOT nhận `tenant_id` hoặc `workspace_id` từ tham số do phía gọi cung cấp khi xác định phạm vi đọc.

**RF-82** — Hệ thống SHALL kiểm tra quyền ở tầng máy chủ cho mọi thao tác đọc số liệu tần suất, nộp giải trình, và quyết định duyệt.

**RF-83** — Hệ thống SHALL tách bạch kiểm tra quyền hạn với kiểm tra vai trò thẩm quyền: có quyền gọi thao tác duyệt không đồng nghĩa với có thẩm quyền duyệt trường hợp cụ thể đó (RF-61).

**RF-84** — Hệ thống SHALL ghi sự kiện audit cho mọi thao tác làm thay đổi trạng thái chặn của một người dùng, gồm cả việc gỡ chặn do đổi cấu hình theo B-10.

---

### 7.11 Ngôn từ, quyền riêng tư, và giới hạn sử dụng

> Mục này là **ràng buộc bắt buộc**, không phải khuyến nghị về văn phong. Nó nâng chuẩn đã tồn tại trong `packages/python/dw_tender/tests/unit/test_repeat_purchase.py:77` — test `test_the_question_asks_for_context_not_an_explanation_of_wrongdoing` — thành yêu cầu hệ thống. Lý do gốc, theo docstring của `repeat_purchase.py`: đây không phải công cụ phát hiện gian lận, và **một lần báo nhầm tốn kém hơn một lần bỏ sót**.

**RF-90** — Hệ thống SHALL diễn đạt mọi thông điệp hướng tới người tạo hồ sơ dưới dạng câu hỏi về bối cảnh và đề nghị hỗ trợ, SHALL NOT diễn đạt dưới dạng cáo buộc hay phán xét.

**RF-91** — Hệ thống SHALL NOT dùng các từ "vi phạm", "sai phạm", "lách", "chia nhỏ" trong bất kỳ văn bản nào hiển thị cho người dùng, ở giao diện web cũng như trên các kênh chat.

**RF-92** — Hệ thống SHALL luôn cho phép người tạo xem số liệu tần suất của chính mình, không phụ thuộc vai trò.

**RF-93** — WHERE Hệ thống hiển thị số liệu tần suất của một người cho một người khác, Hệ thống SHALL chỉ hiển thị cho các vai trò được liệt kê tường minh trong quy chế.

**RF-94** — Hệ thống SHALL NOT xếp hạng, chấm điểm, hay so sánh người dùng với nhau dựa trên số lần bị trả lại.

**RF-95** — Hệ thống SHALL NOT gắn định danh người dùng làm nhãn của bất kỳ chỉ số đo lường nào, do yêu cầu nhãn có lực lượng thấp trong `packages/python/dw_observability/src/dw_observability/metrics.py`.

---

### 7.12 Quan sát và vận hành

**RF-96** — Hệ thống SHALL phát chỉ số đếm cho các sự kiện: ghi nhận lần trả lại, kích hoạt chặn mềm, kích hoạt chặn cứng, nộp giải trình, duyệt giải trình, từ chối giải trình — với nhãn ở mức tenant và nhóm nguyên nhân.

**RF-97** — Hệ thống SHALL ghi `policy_version` và định danh run vào vết quan sát của mỗi lần đánh giá ngưỡng.

**RF-98** — IF việc tính tần suất thất bại vì lỗi hạ tầng, THEN Hệ thống SHALL cho thao tác đi tiếp bình thường, SHALL ghi lỗi ở mức cảnh báo, và SHALL NOT áp dụng chặn mềm hay chặn cứng.

**RF-99** — Hệ thống SHALL phân biệt được trong nhật ký giữa "không có lần trả lại nào" và "không tính được tần suất", SHALL NOT gộp hai tình huống này thành một kết quả.

> **Ghi chú về RF-98 và RF-99.** Đây là hệ quả trực tiếp của khoảng trống 6.3 trong `docs/architecture/dw01-hsmt-rag-flow.vi.md`: hiện tại "hạ tầng chết" và "không có kết quả" nhìn giống hệt nhau ở phía nghiệp vụ. Một cơ chế **chặn người dùng** không được phép mắc lại lỗi đó.

---

## 8. Ràng buộc dữ liệu

Không phải thiết kế lược đồ. Đây là các ràng buộc mà bất kỳ thiết kế nào cũng phải thoả.

**8.1 Đa tenant.** Mọi bảng mới có `tenant_id UUID NOT NULL` và `workspace_id UUID NOT NULL`, bật `ENABLE ROW LEVEL SECURITY` và `FORCE ROW LEVEL SECURITY`, kèm policy `tenant_isolation_<table>` theo đúng khuôn của `db/migrations/versions/0007_preparation.py`.

**8.2 Bất biến.** Bảng lần trả lại và bảng bản giải trình là append-only. Vai trò chạy ứng dụng **không được cấp** `UPDATE` và `DELETE` trên hai bảng này, theo đúng tiền lệ `REVOKE UPDATE, DELETE ON platform.audit_events FROM dw_app` trong migration `0001`.

**8.3 Thời gian.** Mọi mốc thời gian lưu ở dạng có múi giờ. Từ chối giá trị naive, theo đúng ràng buộc `__post_init__` của `AuditEvent` (`packages/python/dw_platform/src/dw_platform/domain/audit.py`).

**8.4 Chỉ mục.** Cần chỉ mục phục vụ truy vấn "các lần trả lại của người tạo X trong N ngày gần nhất", theo tiền lệ `ix_audit_events_tenant_time (tenant_id, occurred_at)`.

**8.5 Bảng đôi.** Mỗi migration Alembic phải có bản sao SQLAlchemy Core tương ứng trong `.../adapters/preparation/tables.py`, theo quy tắc đã ghi trong docstring của chính tập tin đó: _"Mirrors migration 0007 — change both together."_

**8.6 Không dữ liệu suy diễn được lưu trùng.** Trạng thái chặn mềm/chặn cứng là **kết quả tính toán** từ các bản ghi lần trả lại, không phải một cột trạng thái được cập nhật tay — trừ phần gỡ chặn ở RF-62, vốn là một sự kiện có thật cần lưu.

---

## 9. Yêu cầu phi chức năng

| Mã    | Yêu cầu                                                                                                                                                     |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| NFR-1 | Tính tần suất khi mở trang hồ sơ không được làm chậm trang một cách cảm nhận được; nếu vượt ngân sách thời gian thì trả kết quả rỗng theo RF-98 thay vì chờ |
| NFR-2 | Phép đếm tất định: cùng tập bản ghi và cùng mốc thời gian tham chiếu cho cùng kết quả (RF-15)                                                               |
| NFR-3 | Fail-open tuyệt đối: không bao giờ chặn người dùng vì lỗi hạ tầng (RF-98)                                                                                   |
| NFR-4 | Logic đếm và logic ngưỡng là hàm thuần, không I/O, kiểm thử được bằng unit test — theo đúng khuôn `find_repeat(...)` hiện có                                |
| NFR-5 | Giữ ranh giới kiến trúc: `dw_tender` không phụ thuộc `dw_work_ops`; tầng `domain` không import FastAPI/SQLAlchemy/LangGraph                                 |
| NFR-6 | Có test cách ly tenant dạng phủ định: tenant A không đọc được bản ghi lần trả lại và bản giải trình của tenant B                                            |
| NFR-7 | Thêm endpoint thì phải sinh lại ảnh chụp OpenAPI (`contracts/openapi/openapi.json`) và client TypeScript                                                    |

---

## 10. Trường hợp biên và yêu cầu phủ định

| #    | Tình huống                                                 | Hành vi mong đợi                                                                           |
| ---- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| B-1  | Hồ sơ bị trả lại rồi sau đó bị xoá                         | Bản ghi lần trả lại vẫn còn và vẫn được đếm (RF-16)                                        |
| B-2  | Người tạo chuyển sang workspace khác                       | Số đếm không mang theo; mỗi workspace đếm riêng (RF-14)                                    |
| B-3  | Ngưỡng bị hạ xuống trong lúc một người đang bị chặn cứng   | Chặn cứng vẫn giữ; chỉ gỡ bằng duyệt giải trình (RF-45)                                    |
| B-4  | Ngưỡng bị nâng lên, người đang bị chặn nay dưới ngưỡng mới | Như B-3. Quyết định chặn đã ghi kèm `policy_version` cũ (RF-25)                            |
| B-5  | Hai lần trả lại xảy ra gần như đồng thời trên hai hồ sơ    | Cả hai đều được ghi; ngưỡng đánh giá lại sau mỗi lần ghi; thông báo chống trùng theo RF-72 |
| B-6  | Hồ sơ do người A nộp thay mặt người B                      | Đếm theo người tạo được lưu trên hồ sơ, không theo người thao tác (RF-46)                  |
| B-7  | Người tạo đồng thời có vai trò người duyệt                 | Không tự duyệt giải trình của chính mình (RF-64)                                           |
| B-8  | Quy chế bật tính năng giữa chừng, dữ liệu lịch sử đã có    | **Câu hỏi mở** — xem §13.3                                                                 |
| B-9  | Người duyệt trả lại nhầm rồi tự sửa ngay                   | Bản ghi không xoá được (RF-07). Cần một cơ chế đánh dấu "trả nhầm" — **câu hỏi mở** §13.5  |
| B-10 | Tính năng bị tắt trong lúc có người đang bị chặn cứng      | Chặn được gỡ theo RF-24; ghi audit việc gỡ do đổi cấu hình                                 |

---

## 11. Ma trận truy vết

| User story | Mã yêu cầu                                         | Cách kiểm chứng                                                                               |
| ---------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| US-1       | RF-01 … RF-08                                      | Unit test cho bản ghi lần trả lại; integration test giao dịch chung; test phủ định lý do rỗng |
| US-2       | RF-10 … RF-16, RF-90, RF-92                        | Unit test hàm đếm thuần với dữ liệu dựng sẵn; test tất định chạy hai lần                      |
| US-3       | RF-30 … RF-36, RF-91                               | Unit test chọn nhóm nguyên nhân và gợi ý; test chuỗi hiển thị không chứa từ cấm               |
| US-4       | RF-40 … RF-47, RF-98                               | Integration test API trả lỗi khi chặn cứng; test fail-open khi kho dữ liệu lỗi                |
| US-5       | RF-70 … RF-76                                      | Unit test khoá chống trùng; test nhánh lời gọi hành động của bộ gửi Zalo                      |
| US-6       | RF-20 … RF-25                                      | Unit test bộ nạp quy chế: thiếu trường, sai kiểu, ngưỡng 0                                    |
| US-7       | RF-50 … RF-57, RF-60 … RF-66, RF-80 … RF-84, RF-93 | Test phân tách trách nhiệm; test nhận xét rỗng; test quyết định hai lần; test cách ly tenant  |
| US-8       | RF-02, RF-33, RF-34, RF-35                         | Unit test hoà điểm giữa các nhóm nguyên nhân; test nhóm không có gợi ý                        |
| Xuyên suốt | RF-80 … RF-84, RF-90 … RF-99                       | Test chuẩn ngôn từ theo khuôn `test_repeat_purchase.py:77`; kiểm nhãn chỉ số                  |

---

## 12. Definition of Done

Coi là đã đáp ứng đặc tả khi:

- [ ] Trả lại hồ sơ ở cả ba chốt đều sinh bản ghi bất biến, kiểm chứng bằng integration test.
- [ ] Logic đếm và logic ngưỡng là hàm thuần, có unit test phủ cả biên (đúng ngưỡng, dưới ngưỡng một đơn vị, trên ngưỡng).
- [ ] Chặn mềm không cản trở thao tác nào; chặn cứng từ chối đúng hai loại thao tác và không hơn.
- [ ] Bản giải trình nộp được, duyệt được, và phân tách trách nhiệm có test phủ định.
- [ ] Ngưỡng chỉnh được qua quy chế; đặt 0 thì tính năng tắt sạch, có test.
- [ ] Test cách ly tenant dạng phủ định pass cho cả bảng lần trả lại và bảng bản giải trình.
- [ ] Test chuẩn ngôn từ pass: không chuỗi hiển thị nào chứa từ trong RF-91.
- [ ] Fail-open có test: kho dữ liệu lỗi thì thao tác vẫn đi tiếp.
- [ ] Ảnh chụp OpenAPI và client TypeScript sinh lại, biên dịch pass.
- [ ] Thêm loại sự kiện thông báo mới thì `_reply_hint` của bộ gửi Zalo có nhánh tương ứng, có test.
- [ ] `policy_version` của quy chế mới xuất hiện trong release manifest — kèm việc trả nợ §5.5 nếu quy chế đặt trong thư mục lồng.
- [ ] Tài liệu này được cập nhật nếu thiết kế buộc phải lệch khỏi yêu cầu nào; lệch về kiến trúc thì kèm ADR.

---

## 13. Câu hỏi mở

**13.1 Con số ngưỡng chính thức.** Giá trị ở RF-22 là điểm khởi đầu do kỹ thuật đề xuất. Bộ phận mua sắm cần chốt dựa trên số liệu thật: hiện mỗi tháng có bao nhiêu lần trả lại, phân bố theo người tạo ra sao. **Người quyết: trưởng bộ phận mua sắm.**

**13.2 Ai là người hỗ trợ mặc định.** RF-70 nói "vai trò cấu hình trong quy chế", nhưng cần chốt giá trị mặc định: `procurement_head`, hay người quản lý trực tiếp của người tạo? Phương án thứ hai cần dữ liệu tổ chức mà hệ thống hiện chưa có.

**13.3 Có hồi tố không.** Khi bật tính năng lần đầu, có tính các lần trả lại đã xảy ra trước đó không? Tính thì có thể chặn cứng ai đó ngay ngày đầu — trải nghiệm rất xấu. Không tính thì cần một mốc thời gian bắt đầu tường minh. **Đề xuất của kỹ thuật: không hồi tố, ghi mốc bật tính năng vào quy chế.**

**13.4 Bản giải trình lưu bao lâu.** Đây là dữ liệu nhân sự nhạy cảm. Cần chính sách lưu trữ và xoá, thống nhất với bộ phận pháp chế.

**13.5 Xử lý trả nhầm.** RF-07 cấm xoá bản ghi. Nếu người duyệt bấm nhầm, cần một cơ chế đánh dấu vô hiệu — bản ghi vẫn còn nhưng không tính vào ngưỡng — kèm lý do và audit. Có cần trong bản đầu không?

**13.6 Nhóm nguyên nhân lấy từ đâu.** RF-02 yêu cầu danh mục đóng. Có thể tái dùng các mã đã có trong `Finding.code` của `readiness.py` (`no_package`, `criteria_weight`, `supplier_shortfall`, `open_clarification`…), hoặc định nghĩa danh mục riêng hướng nghiệp vụ hơn. **Người quyết: bộ phận mua sắm cùng kỹ thuật.**
