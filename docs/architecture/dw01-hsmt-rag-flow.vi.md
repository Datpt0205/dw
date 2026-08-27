# DW01 — luồng tạo HSMT và đường đi của luật vào Qdrant

Tài liệu này mô tả **logic xử lý thực tế trong code**, dùng làm nền để viết
requirement. Mọi trích dẫn `file:dòng` đều đã đối chiếu với source tại thời điểm viết
(2026-08-24). Đây là tài liệu mô tả hiện trạng, **không phải đề xuất thiết kế**.

> **Cập nhật 2026-08-25 — phần luật đã đổi nguồn.** Tài liệu này viết khi mọi truy vấn
> `domain="legal"` còn đọc corpus Qdrant. Từ `legal_sources@1.1.0.yaml`, bảng định
> tuyến nằm trong config và `legal` đi ra **chuỗi nhà cung cấp tìm kiếm**
> (serper → tavily → brave), corpus lùi về làm đường lui cuối. Mục 1
> (nửa ingest) vẫn đúng nguyên vẹn cho `policy` và `tender`; mục 3 (nửa retrieval) vẫn
> đúng về node nào gọi gì, chỉ khác chỗ **`legal` lấy đoạn văn từ đâu**. Xem
> [§8 bên dưới](#8-cập-nhật-2026-08-25--chuỗi-nhà-cung-cấp-thay-cho-một-sợi-dây).

---

## 0. Bức tranh một trang

Có **hai nửa** tách rời nhau, gặp nhau đúng một chỗ:

```
   NỬA INGEST                              NỬA RETRIEVAL
   (luật → Qdrant)                         (soạn HSMT → truy căn cứ)

   Upload API  ─┐                          3 node tiêu thụ, 5 truy vấn:
                ├→ KnowledgeGateway ←──────┤  draft_procurement_approach  ×3
   seed script ─┘   .ingest_document()     │  draft_solicitation_package  ×1
                          │                │  draft_evaluation_criteria   ×1
                    chunk → embed          │       │
                          │                │       ↓ chỉ nhánh ×3 đi tiếp:
                    ┌─────┴─────┐          │  LLM CHÉP số ra khỏi đoạn văn
                Postgres     Qdrant        │       │
              (nguồn sự thật) (vector)     │  verified_constraint() kiểm chứng
                                           │       │
                                           │  code tất định áp dụng con số
                                           └──────→ timeline HSMT + gate CP2
```

`KnowledgeGateway` (`packages/python/dw_knowledge/src/dw_knowledge/gateway.py`) là
**điểm thắt cổ chai có chủ đích**: nơi duy nhất được phép dựng filter tenant/ACL.

---

## 1. Nửa ingest — luật vào Qdrant bằng đường nào

### 1.1 Hai lối vào, cùng một đích

**Lối A — qua API (đường chính thức, có phân quyền)**

`POST /api/v1/knowledge/documents` — `apps/api/src/dw_api/routes/v1/knowledge.py:89`

Form nhận: `file`, `title`, `domain`, `classification`, `source_version`, `scope`.

Ba chốt chặn ngay tại route, **trước khi** đụng tới dữ liệu:

1. `authorization.require(action="knowledge.write")`
2. `scope` chỉ được là `"tenant"` hoặc `"global"` — khác là `DomainError`
3. **`scope="global"` đòi role `platform_admin`.** Đây là chốt quan trọng nhất về
   nghiệp vụ: văn bản luật là tài liệu _mọi tenant đọc được_, nên một thành viên tenant
   thường không được phép gieo nội dung mà cả hệ thống sẽ đọc.

Rồi: đọc bytes → chặn file rỗng và quá cỡ → `put_object` vào MinIO theo key
`{tenant}/{workspace}/uploads/{job_id}/{filename}` → `enqueue` một job vào
`knowledge.ingest_jobs` → trả **202** kèm `job_id`. API **không** parse, **không** embed.

**Lối B — qua script (đường demo/seed)**

`scripts/seed_knowledge.py` gọi thẳng `gateway.ingest_document()`, bỏ qua hàng đợi.
Nội dung luật nằm ngay trong file (hằng `LUAT_DAU_THAU`, `QUY_CHE_NOI_BO`) và được
ingest với:

| Tài liệu                     | domain   | scope        | classification |
| ---------------------------- | -------- | ------------ | -------------- |
| Luật Đấu thầu — trích lục    | `legal`  | **`global`** | `internal`     |
| Quy chế mua sắm nội bộ Alpha | `policy` | `tenant`     | `internal`     |

Đúng cặp `domain`/`scope` này là thứ quyết định luồng HSMT có thấy được tài liệu hay không.

### 1.2 Worker nuốt hàng đợi

Consumer `knowledge_ingest` đăng ký ở `apps/worker/src/dw_worker/main.py:29`; thân ở
`apps/worker/src/dw_worker/consumers/ingest.py`. Mỗi tick nó `claim_next()` tối đa
`batch_size` job, xử lý, và **nuốt exception để tiếp tục rút hàng đợi** — job hỏng bị
`mark_failed` kèm tên lỗi chứ không chặn các job sau.

Consumer chỉ bật khi cả `database_url` và `s3_endpoint_url` có giá trị; thiếu một trong
hai thì worker log `knowledge ingest disabled` và **im lặng bỏ qua mọi upload**.

### 1.3 Bên trong `ingest_document` — `gateway.py:126`

1. **Chunk theo cấu trúc** — `chunking.py:137` `structure_aware_chunks()`. Cắt theo cấp
   heading Markdown, kiểu cha–con: chunk lá giữ `section_path` (đường dẫn mục) và số thứ
   tự toàn cục. Với văn bản luật điều này quan trọng — "Điều 45 khoản 1" phải đi kèm
   đoạn văn, nếu không đoạn trích mất ngữ cảnh điều khoản.
2. **Embed** bằng BGE-M3 qua TEI (1024 chiều).
3. **Ghi Postgres** — `knowledge.documents` + `knowledge.chunks`. **Postgres là nguồn sự
   thật; vector chỉ là dẫn xuất.** Đó là lý do `scripts/knowledge_reindex.py` dựng lại
   được toàn bộ Qdrant từ Postgres.
4. **Upsert Qdrant.**

**Versioning có thật và chạy đúng** (`gateway.py:169–176`): ingest lại cùng `doc_key`
sẽ _supersede_ bản cũ — `is_current=False`, `effective_to=now()`,
`superseded_by=<id mới>`. Bản mới `is_current=True`, `effective_from=now()`.

`INDEX_VERSION` là **hằng trong code** (`gateway.py:54` = `"2026-07-25.structure-1"`),
nằm trong id của chunk. Đổi cách chunk ⇒ phải bump hằng này ⇒ phải chạy tay
`knowledge_reindex.py`.

---

## 2. Mô hình filter — chỗ duy nhất được dựng filter

`build_trusted_filter()` — `gateway.py:91`. Nó dựng filter **chỉ từ `AccessContext` đã
xác thực**, không bao giờ từ input người dùng hay output model.

`SearchQuery` (`contracts.py:35`) cố tình **không có** trường tenant/workspace/ACL —
comment trong code nói thẳng: "callers (including model output) can never override them".
Prompt injection không thể mở rộng phạm vi đọc, vì không có chỗ để chèn.

Payload mỗi điểm Qdrant mang: `tenant_id`, `workspace_id`, `domain`, `classification`,
`scope`, `is_deleted`.

Điều kiện đọc (`adapters/qdrant_index.py:165–200`):

| Mệnh đề    | Nội dung                                                                   |
| ---------- | -------------------------------------------------------------------------- |
| `must`     | `domain` ∈ {domain yêu cầu, `shared`}                                      |
| `must`     | `classification` ∈ thang clearance của người gọi                           |
| `should`   | (`tenant_id` khớp **và** `workspace_id` khớp) **HOẶC** `scope == "global"` |
| `must_not` | `is_deleted == true`                                                       |

Thang clearance (`gateway.py:46` `clearance_allows`) là danh sách có thứ tự
`internal < confidential < restricted`; clearance cấp nào đọc được cấp đó trở xuống, và
**fail closed** — clearance lạ chỉ được `internal`.

> **`scope="global"` chính là cơ chế làm cho luật dùng chung được còn quy chế nội bộ thì
> không.** Đây là điểm mấu chốt nếu bạn viết requirement về kho luật đa tenant.

---

## 3. Nửa retrieval — HSMT dùng luật ở bước nào

### 3.1 Toàn cảnh đồ thị — 17 node, không bỏ node nào

`packages/python/dw_tender/src/dw_tender/workflows/preparation_v1/graph.py` dựng đồ thị
(`GRAPH_VERSION = "1.0.0"`, `graph.py:18`) và trả về **chưa compile**; runner mới compile
nó cùng SQL checkpointer, nên mọi lần dừng đều bền vững.

```
START
  ↓
load_case → extract_requirements → completeness_check
  ↓
draft_procurement_approach              ★ RAG ×3 → LLM chép → code kiểm chứng
  ↓
approach_gate ──(gate trượt)──→ close_incomplete → END
  ├─ uỷ quyền P6 ───────────→ apply_cp1      ← bỏ qua interrupt, vẫn ghi audit
  └─ gate đạt ──→ cp1_review ⏸ ──→ apply_cp1
                                     ├─ từ chối ─→ close_failed → END
                                     └─ duyệt ───→ (A)

(A) draft_solicitation_package          ★ RAG ×1
      ↓
    draft_evaluation_criteria           ★ RAG ×1
      ↓
    build_supplier_shortlist → run_risk_check
      ↓
    package_gate ──(đạt hay trượt đều đi tiếp)──→ cp2_review ⏸
                                                       ↓
                                                    apply_cp2
                                                       ├─ từ chối ─→ close_failed → END
                                                       └─ duyệt ─→ finalize_official → END
```

`★` = node có gọi `_cite()` (chạm Qdrant) · `⏸` = node có gọi `interrupt()` (dừng chờ người).

**Đồ thị dừng ở `finalize_official`.** Phát hành HSMT, addendum CP3, mở thầu CP4 và bàn
giao sang DW02 đều là handler giao dịch + connector, **nằm ngoài graph** — không có node
nào cho chúng. (Lưu ý: `docs/overview/DW01_TECHNICAL_OVERVIEW.md:155` ghi
`preparation_v1` là "CP1→CP4"; điều đó không đúng với code.)

### 3.2 Mười bảy node — node nào gọi LLM, node nào chạm luật

Tên node trong bảng là **chuỗi thật** truyền vào `add_node` (`graph.py:72-73`); không có
alias, tên node trùng tên method trên `PreparationNodes`.

| #   | Node                         | `nodes.py` | Làm gì                                                                                | Dùng gì                                                                                  | Ghi vào state                                                                          |
| --- | ---------------------------- | ---------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| 1   | `load_case`                  | `:449`     | Nạp case, đọc PR đã duyệt từ object storage, gom artifact làm rõ + NCC ứng viên       | chỉ đọc DB, không commit                                                                 | `pr_text`, `estimated_value_minor`, `deadline`, `owner_name`, `supplier_candidates`, … |
| 2   | `extract_requirements`       | `:494`     | Bóc yêu cầu và các chỗ `CHƯA RÕ` ra khỏi văn bản PR                                   | LLM `PreparationExtraction`; fallback parse dòng                                         | `requirements`, `unknowns`                                                             |
| 3   | `completeness_check`         | `:639`     | Dựng danh sách câu hỏi làm rõ, đánh dấu câu **chặn**                                  | thuần code                                                                               | `clarifications`                                                                       |
| 4   | `draft_procurement_approach` | `:683`     | Chọn hình thức, chốt cửa sổ nộp, dựng timeline                                        | **★ RAG ×3** + LLM `LegalConstraintExtraction` + rule pack `select_method`               | `method_key`, `min_suppliers`, `solicitation_window_days`, `legal_constraints`         |
| 5   | `approach_gate`              | `:843`     | Chấm gate CP1 tất định (7 điều kiện), dựng `cp1_payload`                              | rule pack `approach_gate()` + LLM `ReviewRecommendation` (**cố vấn**)                    | `approach_gate`, `cp1_payload`, _(P6)_ `cp1_decision`                                  |
| 6   | `cp1_review`                 | `:1070`    | Dừng, chờ người duyệt                                                                 | **⏸ `interrupt(cp1_payload)`**                                                           | `cp1_decision`                                                                         |
| 7   | `apply_cp1`                  | `:1074`    | Ghi trạng thái case theo quyết định CP1, bắn card kết quả                             | thuần code                                                                               | — (trả `{}`)                                                                           |
| 8   | `draft_solicitation_package` | `:1123`    | Soạn nội dung HSMT                                                                    | LLM `SolicitationDraft` + **★ RAG ×1** + rule pack (điều khoản thanh toán/thuế/cấu trúc) | — (trả `{}`; ghi artifact)                                                             |
| 9   | `draft_evaluation_criteria`  | `:1200`    | Dựng tiêu chí chấm, ép Σ trọng số = 100                                               | LLM `CriteriaDraft` (**loại nếu Σ ≠ 100**) + **★ RAG ×1** + rule pack                    | `criteria`                                                                             |
| 10  | `build_supplier_shortlist`   | `:1248`    | Map NCC ứng viên thành shortlist trạng thái `pending_verification`                    | thuần code                                                                               | `shortlist`                                                                            |
| 11  | `run_risk_check`             | `:1279`    | 3 kiểm tra tất định: cạnh tranh tối thiểu · xung đột lợi ích · trung lập tiêu chí     | thuần code                                                                               | `risk`                                                                                 |
| 12  | `package_gate`               | `:1311`    | Chấm gate CP2 tất định, dựng `cp2_payload`                                            | rule pack `solicitation_gate()` + LLM `ReviewRecommendation` (**cố vấn**)                | `package_gate`, `cp2_payload`                                                          |
| 13  | `cp2_review`                 | `:1473`    | Dừng, chờ người duyệt                                                                 | **⏸ `interrupt(cp2_payload)`**                                                           | `cp2_decision`                                                                         |
| 14  | `apply_cp2`                  | `:1477`    | Ghi trạng thái case theo quyết định CP2                                               | thuần code                                                                               | — (trả `{}`)                                                                           |
| 15  | `finalize_official`          | `:1514`    | Dựng manifest (mọi artifact + `rule_pack_version`), ghi 2 object, khoá bản chính thức | thuần code                                                                               | `official_manifest`, `export_ref`                                                      |
| 16  | `close_failed`               | `:1585`    | không làm gì                                                                          | —                                                                                        | — (trả `{}`)                                                                           |
| 17  | `close_incomplete`           | `:1591`    | không làm gì                                                                          | —                                                                                        | — (trả `{}`)                                                                           |

Bốn điều đáng chú ý trong bảng trên:

- **Hai node đóng là no-op thật.** `close_failed`/`close_incomplete` chỉ `return {}` —
  trạng thái case đã được `apply_cp1`/`apply_cp2`/`approach_gate` ghi xong từ trước. Chúng
  tồn tại để đồ thị có đích rõ ràng, không phải để làm việc.
- **`extract_requirements` chạy lại không tốn LLM.** Đã có artifact `DEMAND_SNAPSHOT` thì
  node trả thẳng nội dung cũ, không gọi model, không ghi gì (`nodes.py:504-509`).
- **LLM ở hai gate là cố vấn, không phải người quyết.** `_run_review` (`nodes.py:354`)
  chạy dưới một `RunContext` **riêng** (`worker_id="dw01.review_agent"`, `run_id` mới) và
  chỉ sinh khuyến nghị; verdict pass/fail vẫn do `rules.py` tính.
- **`run_risk_check` luôn để "Xung đột lợi ích" = `ok: False`** (`nodes.py:1291-1295`) —
  cố ý, vì chưa có nguồn dữ liệu kiểm tra; nên `risk.all_ok` thực tế không bao giờ `True`.
  Gate CP2 **không** đọc `risk`, nên điều này không chặn luồng, chỉ hiện trên card.

### 3.3 Cạnh — và chỗ bất đối xứng đáng ngờ

**15 cạnh thẳng:**

| Cạnh                                                                                                                                                  | Dựng ở                                               |
| ----------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `START → load_case`                                                                                                                                   | `graph.py:75`                                        |
| `load_case → extract_requirements → completeness_check → draft_procurement_approach → approach_gate` (4 cạnh)                                         | `graph.py:76-77`, qua `pairwise(_INTAKE_TO_CP1[:5])` |
| `cp1_review → apply_cp1`                                                                                                                              | `graph.py:87`                                        |
| `draft_solicitation_package → draft_evaluation_criteria → build_supplier_shortlist → run_risk_check → package_gate → cp2_review → apply_cp2` (6 cạnh) | `graph.py:97-98`, qua `pairwise(_CP1_TO_CP2)`        |
| `finalize_official → END`, `close_failed → END`, `close_incomplete → END`                                                                             | `graph.py:105-107`                                   |

Lát cắt `[:5]` là có chủ đích: nó dừng đúng ở `approach_gate` để node này không bị nối
cạnh thẳng, vì cạnh ra của nó là cạnh điều kiện.

**3 cụm cạnh điều kiện:**

| Router                       | `graph.py` | Đọc state                              | Nhánh ra                                                                            |
| ---------------------------- | ---------- | -------------------------------------- | ----------------------------------------------------------------------------------- |
| `_route_after_approach_gate` | `:45`      | `approach_gate.passed`, `cp1_decision` | `close_incomplete` (trượt) · `apply_cp1` (đã có sẵn quyết định — P6) · `cp1_review` |
| `_route_after_cp1`           | `:40`      | `cp1_decision.approved`                | `draft_solicitation_package` · `close_failed`                                       |
| `_route_after_cp2`           | `:55`      | `cp2_decision.approved`                | `finalize_official` · `close_failed`                                                |

> **`package_gate` KHÔNG có cạnh điều kiện.** `graph.py:97-98` nối thẳng
> `package_gate → cp2_review`, nên gói **trượt gate CP2 vẫn chạm `interrupt` và vẫn tạo
> approval request** — node chỉ đổi card thành "⚠️ Gate CP2 CHƯA ĐẠT"
> (`nodes.py:1460-1468`) rồi đẩy quyết định sang người. Phía CP1 có `close_incomplete` để
> đóng sớm; **phía CP2 không có đối ứng.** Đây là bất đối xứng lớn nhất giữa hai chốt.

Còn lại: **không subgraph, không `RetryPolicy`, không `interrupt_before/after`, không cạnh
lùi** — đồ thị là DAG thuần. Khả năng chịu lỗi nằm trong từng node bằng `try/except` rồi
suy biến (`_cite`, `_run_review`, `_extract_legal_constraints`, `_llm_*` đều nuốt lỗi và
chạy tiếp), chứ không phải bằng cơ chế retry của LangGraph.

Vòng lặp "trả lời làm rõ rồi chạy tiếp" **không phải cạnh lùi**: `close_incomplete` kết
thúc run, người dùng trả lời qua API, và handler khởi động một **run mới** với `run_id` /
`thread_id` mới (`nodes.py:1591-1597` ghi rõ ý đồ này). Tính idempotent của lần chạy lại
dựa vào short-circuit ở `extract_requirements` và dedupe theo content-hash khi thêm
artifact (`nodes.py:226-231`).

### 3.4 Hai chỗ dừng — và đường vòng bỏ qua một chỗ

Toàn đồ thị chỉ có **đúng 2 lời gọi `interrupt()`**: `nodes.py:1071` và `nodes.py:1474`.
Payload là `cp1_payload` / `cp2_payload` do node gate dựng sẵn từ trước — bản thân hai
node gate **không bao giờ** gọi `interrupt`.

Chuỗi dừng → duyệt → chạy tiếp:

1. `interrupt(payload)` ⇒ LangGraph ghi `__interrupt__` vào state và dừng graph.
2. `langgraph_runner.py:148-201` đọc `interrupts[0].value`, tạo `ApprovalRequest` với
   `approval_type` / `reason` lấy từ payload, đặt run về `WAITING_APPROVAL` + audit.
3. Người duyệt quyết qua `approval_flow.py`, nơi kiểm **tách bạch nhiệm vụ** (người tạo
   run không được tự duyệt CP của chính mình) và **thẩm quyền** (`payload["required_role"]`
   phải nằm trong roles của người duyệt); `preparation.*` bắt buộc có comment.
4. `graph.ainvoke(Command(resume={"approved": ..., "comment": ...}), config)`
   (`langgraph_runner.py:142`) đưa graph vào lại đúng node `cp*_review`, và `interrupt()`
   **trả về chính dict đó**.

Checkpoint nằm ở PostgreSQL nên bước 4 sống sót qua restart tiến trình.

**Đường vòng P6 (uỷ quyền tự chủ) bỏ qua CP1.** Điều kiện tính ngay trong `approach_gate`
(`nodes.py:922-928`) — phải đúng **tất cả**:

```python
autopilot = (result.passed                                    # gate tất định đạt
    and review is not None                                    # có khuyến nghị của LLM cố vấn
    and review.recommendation == "approve"                    # và khuyến nghị đó là duyệt
    and method.min_suppliers == 1                             # rủi ro thấp: mua sắm trực tiếp
    and self.services.autonomy_profile == "autonomous_demo")  # hồ sơ autonomy cho phép
```

Khi đúng, node trả sẵn `cp1_decision` với `mode="delegated_autonomy"`,
`decided_by_agent="dw01.review_agent"` (`nodes.py:1055-1066`) ⇒ router nhảy thẳng
`apply_cp1`: **không interrupt, không approval request**. Người lẽ ra phải duyệt vẫn nhận
card FYI kèm đường override. Mặc định hệ thống là `governed_production` (`services.py:42`),
tức luôn dừng chờ người. **CP2 không có đường vòng nào.**

### 3.5 Năm điểm chạm RAG — chỉ ba trong số đó được kiểm chứng

Đây là chỗ dễ hiểu nhầm nhất của cả luồng. `_cite()` được gọi ở **5 chỗ trên 3 node**:

| Node                         | `nodes.py`             | `domain`                | Kết quả đi đâu                                                                                            |
| ---------------------------- | ---------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------- |
| `draft_procurement_approach` | `:728`, `:735`, `:744` | `legal` ×2, `policy` ×1 | vào prompt `LegalConstraintExtraction` → **`verified_constraint()`** → con số áp vào timeline và gate CP2 |
| `draft_solicitation_package` | `:1184`                | `legal`                 | gắn thẳng vào `content["references"]` của artifact + `grounding_status`                                   |
| `draft_evaluation_criteria`  | `:1234`                | `legal`                 | gắn thẳng vào `content["references"]` của artifact + `grounding_status`                                   |

> **Chỉ ba truy vấn ở `draft_procurement_approach` đi qua hợp đồng chống bịa ở §4.** Hai
> truy vấn còn lại chỉ _đính kèm_ trích đoạn vào tài liệu — không có bước nào buộc đoạn
> trích phải liên quan tới nội dung đang soạn, và không con số nào từ đó được dùng.

### 3.6 Ba truy vấn, ba ý định khác nhau

Trong `draft_procurement_approach` (`nodes.py:683`):

| #   | `domain` | Câu truy vấn                                                            | Để làm gì                            |
| --- | -------- | ----------------------------------------------------------------------- | ------------------------------------ |
| 1   | `legal`  | `hình thức lựa chọn nhà thầu {method} điều kiện áp dụng`                | căn cứ pháp lý cho hình thức đã chọn |
| 2   | `legal`  | `thời gian chuẩn bị hồ sơ dự thầu tối thiểu kể từ ngày phát hành hồ sơ` | mốc thời gian kiểu Điều 45           |
| 3   | `policy` | `hạn mức phê duyệt phương án mua sắm giá trị {tiền}`                    | quy chế nội bộ về hạn mức duyệt      |

Tách làm hai truy vấn `legal` là có chủ đích: "áp dụng hình thức nào" và "cho bao nhiêu
ngày" là hai câu hỏi khác nhau, gộp lại thì embedding loãng. Kết quả truy vấn 2 được
merge vào truy vấn 1, khử trùng theo cặp `(source_document_id, quote)`.

**Lưu ý: hình thức mua sắm KHÔNG do LLM chọn.** `rules.select_method(value)` là rule pack
tất định (`configs/policies/dw01/procurement_rules_v1.yaml`); RAG chỉ đi tìm _căn cứ_ cho lựa chọn đã có.

### 3.7 Helper `_cite()` — `nodes.py:176`

`top_k=3` **cứng trong code**, không cấu hình được. Trả về citation gọn gồm
`source_document_id`, `source_version`, `quote` (cắt 1200 ký tự — đoạn thật, không phải
teaser), `relevance_score`, `classification`.

**Nuốt mọi exception → trả list rỗng.** Comment ghi rõ ý đồ: "retrieval is best-effort
grounding, not a gate" — không truy được căn cứ thì vẫn soạn tiếp, không chặn nghiệp vụ.

Không có căn cứ nào ⇒ `grounding_status = "not_available"` + `grounding_warning` yêu cầu
người duyệt tự kiểm tra rule pack và tài liệu nguồn trước CP1.

---

## 4. Hợp đồng chống bịa — phần đáng đọc nhất

Nguyên tắc: **"LLM soạn; code tất định quyết."**

### Bước 1 — LLM chỉ được CHÉP

`_extract_legal_constraints()` (`nodes.py:413`) gom các `quote` đã truy hồi, đánh số
`[1] [2] [3]`, rồi gọi model với schema `LegalConstraintExtraction`
(`application/preparation/legal.py`):

```python
min_bid_preparation_days: int | None   # ge=1, le=365
article_ref: str                        # "Điều 45 khoản 1"
source_quote: str                       # câu chứa con số, CHÉP NGUYÊN VĂN
```

Mô tả field nói thẳng với model: chỉ điền **khi con số xuất hiện nguyên văn trong trích
đoạn**. Model không được suy luận ra con số.

### Bước 2 — code kiểm chứng lời chép

`verified_constraint()` — `legal.py:43`. Chỉ nhận khi **cả ba** đúng:

1. `min_bid_preparation_days` không None **và** `source_quote` dài ≥ 15 ký tự
2. Câu trích **xuất hiện nguyên văn** trong một passage đã truy hồi
   (so sánh sau khi chuẩn hoá khoảng trắng + casefold)
3. Con số **nằm trong chính câu trích đó** — regex `(?<!\d)0?{days}(?!\d)`, nên "05"
   tính là 5, còn "150" không khớp với 5

Trượt bất kỳ điều nào ⇒ trả `None` ⇒ vứt bỏ hoàn toàn.

### Bước 3 — code áp dụng

```python
default_window = _solicitation_window_days(method.key)   # nodes.py:81
legal_min      = constraint["min_bid_preparation_days"] if constraint else None
window         = max(default_window, legal_min or 0)
```

Mặc định tất định: `open_tender` 22 ngày · `rfq` 14 ngày · còn lại 7 ngày.

> **`max()` nghĩa là: luật chỉ KÉO DÀI được thời hạn, không bao giờ rút ngắn.** Một trích
> đoạn bịa ra con số nhỏ hơn cũng vô hại. Đây là bất biến an toàn cốt lõi của luồng.

### Bước 4 — hệ quả xuống nghiệp vụ

`deadline_conflict` được đặt khi **cả ba** điều kiện đúng: có constraint đã kiểm chứng,
có `legal_min`, và số ngày An cần hàng (parse từ `"90 ngày"`) **nhỏ hơn** `window`. Thông
báo nêu rõ con số, `article_ref`, và mốc tối thiểu phải đặt.

`timeline` gồm 3 mốc: phát hành (offset 0) → hạn nộp (offset `window`) → đánh giá &
trình duyệt (offset `window + 7`).

### Bước 5 — luật có răng, không chỉ có trích dẫn

`legal_min` đã kiểm chứng không dừng ở việc hiển thị. Nó đi tiếp xuống gate CP2 —
`solicitation_gate()` nhận nó qua tham số `legal_min_window_days`
(`packages/python/dw_tender/src/dw_tender/application/preparation/rules.py:154`):

```python
if (legal_min_window_days is not None
        and submission_window_days
        and submission_window_days < legal_min_window_days):
    failures.append(f"Hạn nộp hồ sơ {submission_window_days} ngày ngắn hơn mức tối thiểu "
                    f"{legal_min_window_days} ngày theo căn cứ pháp lý đã truy xuất.")
```

Docstring của hàm nói thẳng ý đồ: _"the law has teeth, not just a citation"_.

> Hai bất biến khoá nhau. `max()` ở Bước 3 khiến luật **không rút ngắn được** thời hạn;
> `solicitation_gate` ở CP2 khiến gói vi phạm thời hạn **không qua được cửa duyệt**. Cái
> thứ nhất chống trích đoạn bịa; cái thứ hai chống người soạn tự ý bóp thời gian.

Toàn bộ đoạn trích được đẩy lên card Zalo: dòng trạng thái ở DM, các đoạn căn cứ gập vào
thread.

---

## 5. Hiện trạng dữ liệu (đo lúc viết)

| Chỉ số                                   | Giá trị                                     |
| ---------------------------------------- | ------------------------------------------- |
| Qdrant collection                        | `dw_knowledge`, 1024 chiều, **13 điểm**     |
| Tài liệu `domain=legal`, `scope=global`  | 1 — _Luật Đấu thầu — trích lục_, 6 chunk    |
| Tài liệu `domain=policy`, `scope=tenant` | 1 — _Quy chế mua sắm nội bộ Alpha_, 4 chunk |
| Tài liệu `domain=tender`                 | 3, 1 chunk mỗi cái                          |

**Trước ngày 2026-08-24 con số này là 0 tài liệu luật** — `seed_knowledge.py` chưa từng
chạy trên stack này, nên mọi truy vấn `legal`/`policy` đều trả rỗng và HSMT luôn chạy
bằng mặc định tất định với `grounding_status=not_available`. Nếu bạn từng thấy luồng
"không trích được căn cứ nào", đó là nguyên nhân, không phải lỗi logic.

---

## 6. Khoảng trống hiện tại — phần để viết requirement

Đây là những chỗ code **chưa làm**, xếp theo mức ảnh hưởng nghiệp vụ:

**6.1 `effective_from` là thời điểm ingest, không phải ngày luật có hiệu lực.**
Versioning theo `doc_key` chạy đúng, nhưng không mô hình hoá được "Luật 22/2023/QH15 có
hiệu lực từ 01/01/2024". Và retrieval **không lọc theo mốc thời gian nào cả** — không trả
lời được câu "tại ngày phát hành HSMT thì điều khoản nào đang hiệu lực". Với hồ sơ thầu
kéo dài nhiều tháng và luật sửa giữa chừng, đây là khoảng trống lớn nhất.

**6.2 Không có kích hoạt re-index khi văn bản đổi.** `INDEX_VERSION` là hằng trong code;
sửa cách chunk hay đổi model embedding đều phải nhớ chạy tay `knowledge_reindex.py`.
Không có cơ chế phát hiện lệch phiên bản index.

**6.3 `_cite()` nuốt exception im lặng.** "Qdrant chết" và "Qdrant không có kết quả" nhìn
giống hệt nhau ở phía nghiệp vụ — cả hai đều ra `grounding_status=not_available`. Người
duyệt không phân biệt được "chưa có luật trong kho" với "hạ tầng đang hỏng".

**6.4 `top_k=3` cứng.** Không cấu hình được theo domain. Văn bản luật dài, 3 chunk có thể
không đủ phủ một điều khoản có nhiều khoản mục.

**6.5 Chỉ bóc được một loại ràng buộc.** `LegalConstraintExtraction` chỉ có
`min_bid_preparation_days`. Các ràng buộc định lượng khác — số nhà thầu tối thiểu, thời
gian đăng tải, hạn mức chỉ định thầu — **không** đi qua cơ chế kiểm chứng này; chúng nằm
trong rule pack tĩnh `configs/policies/dw01/procurement_rules_v1.yaml`, tách rời khỏi văn bản luật trong kho.

**6.6 Không có đường phản hồi khi trích dẫn sai.** Người duyệt thấy đoạn trích không liên
quan thì không có cách nào đánh dấu, và hệ thống không học được gì.

**6.7 Ingest chỉ có Markdown/text được chunk theo cấu trúc.** `structure_aware_chunks`
cắt theo heading Markdown; văn bản luật dạng PDF/DOCX đi qua parser
(`adapters/composite_parser.py`, `docling_parser.py`) — cần kiểm chứng riêng xem cấu trúc
Điều/Khoản có sống sót qua parser không.

**6.8 Hai trong năm điểm chạm RAG không có hợp đồng kiểm chứng.**
`draft_solicitation_package` (`nodes.py:1184`) và `draft_evaluation_criteria`
(`nodes.py:1234`) gắn thẳng `references` vào artifact kèm `grounding_status`, **không** đi
qua `verified_constraint()`. Không có gì buộc đoạn trích phải liên quan tới nội dung đang
soạn. Trên card, người duyệt không phân biệt được trích dẫn _đã kiểm chứng từng ký tự_
(§4) với trích dẫn _chỉ được đính kèm_.

---

## 7. Thử tay trong 3 lệnh

```bash
DC="docker compose --env-file .env -f infra/compose/docker-compose.yml"

# 1. Nạp corpus luật
$DC exec -T api python - < scripts/seed_knowledge.py
$DC exec -T api python - < scripts/knowledge_reindex.py

# 2. Xem có gì trong kho
$DC exec -T postgres psql -U dw_admin -d dw \
  -c "select title, domain, scope, classification from knowledge.documents order by domain"

# 3. Đếm điểm trong Qdrant
curl -s http://127.0.0.1:6333/collections/dw_knowledge | \
  python3 -c "import sys,json;r=json.load(sys.stdin)['result'];print(r['points_count'],'điểm')"
```

---

## 8. Cập nhật 2026-08-25 — chuỗi nhà cung cấp thay cho một sợi dây

### 8.1 Bảng định tuyến giờ nằm trong config

`configs/knowledge/legal_sources@1.1.0.yaml`:

```yaml
routing:
    legal: web # tra trực tuyến lúc hỏi
    policy: corpus # quy chế công ty — không có trên Google
    tender: corpus # hồ sơ nhà thầu nộp — dữ liệu tenant
    shared: both # domain của chat, trộn xen kẽ
```

Domain không nêu mặc định là `corpus` — fail closed. Trước đó bảng này là ba
`frozenset` nằm trong default của dataclass `LegalSourceRouter`.

### 8.2 Năm điểm chạm RAG, giờ đi đâu

| #   | `nodes.py` | `domain` | Nguồn      |
| --- | ---------- | -------- | ---------- |
| 1   | `:739`     | `legal`  | chuỗi web  |
| 2   | `:746`     | `legal`  | chuỗi web  |
| 3   | `:755`     | `policy` | **Qdrant** |
| 4   | `:1195`    | `legal`  | chuỗi web  |
| 5   | `:1245`    | `legal`  | chuỗi web  |

Bốn trên năm ra web. Đó là toàn bộ phần "migrate" — 7 trong 13 điểm còn lại trong
Qdrant (quy chế nội bộ + tài liệu thầu) **không có nguồn thay thế nào**, và luồng
upload → MinIO → worker → ingest không đụng một dòng.

### 8.3 Chuỗi, và hai cơ chế chặn

`FailoverSearchClient` thử theo đúng thứ tự trong `providers:` — hiện là
`serper → tavily → brave`, xếp theo hạn mức **đo ngày 2026-08-25** chứ không theo
danh tiếng: Serper là khoản cấp một lần nên tiêu trước, Tavily là tầng tự tái tạo duy
nhất không cần thẻ, Brave đòi thẻ nên xuống dưới. `google_cse` tắt vì Google đã đóng
đăng ký mới và ngừng API từ 01/01/2027. Ưu tiên cứng, không
xoay vòng: cùng một câu hỏi phải cho cùng một kết quả, vì khi có người khiếu nại mốc
thời gian dự thầu thì "đã hỏi máy tìm kiếm nào" không nên có đáp án ngẫu nhiên.

| Tín hiệu                | Cơ chế                    | Nghỉ bao lâu |
| ----------------------- | ------------------------- | ------------ |
| Timeout, 5xx, JSON hỏng | `CircuitBreaker` (có sẵn) | 30s          |
| **429 / 403 / 401**     | `ProviderCooldown` (mới)  | 6h           |

Không tự đếm quota trong app: một biến đếm cục bộ lệch khỏi thực tế ngay lần restart
đầu tiên, còn 429 là con số của chính nhà cung cấp và không bao giờ cũ.

Allowlist chạy **bên trong** vòng lặp chuỗi (`accept=` callback), không phải sau nó —
provider trả 10 kết quả mà 0 cái qua được allowlist thì coi như không giúp được gì, và
chỉ chuỗi mới hành động được trên sự thật đó.

### 8.4 Đường lui về corpus, và cách nhận ra nó

`legal` tra web không ra gì → dùng corpus, kèm log WARNING. Bên soạn nhận ra bằng
**sự vắng mặt của `source_uri`** (`_grounding_source()` trong `nodes.py`) và ghi
`content["grounding_source"] = "indexed"`, rồi in lên thẻ CP1:

> 📎 Căn cứ pháp lý lấy từ kho đã lưu trong hệ thống, không phải tra trực tuyến tại
> thời điểm này — hãy đối chiếu hiệu lực trước khi duyệt.

Không thêm trường nào vào `EvidenceRef`: đoạn từ corpus vốn đã không có URL.

### 8.5 §6.8 cũ — đã xử lý, và phần còn lại được ghi rõ

Mục 6.8 ghi nhận hai điểm chạm `:1195` và `:1245` gắn `references` mà không dùng vào việc
gì. Cập nhật 25/08:

**Đã sửa — đoạn tra về giờ đi vào prompt.** Trước đây cả hai node gọi LLM **trước** rồi mới
tra luật, nên đoạn văn không thể tới prompt: nó đã gửi xong rồi. Giờ `_cite()` chạy trước,
và đoạn đã tra được truyền vào qua biến `passages` (`draft_solicitation@1.1.0`,
`draft_criteria@1.1.0`). Cả hai prompt mở đầu bằng dòng "DỮ LIỆU KHÔNG TIN CẬY" — từ khi
đổi sang web search, các đoạn này là HTML tải về từ máy tìm kiếm.

**Đã sửa — `passages()` không còn đòi mọi đoạn phải chứa `N ngày`.** Điều kiện đó giờ bám
vào từng neo (xem `legal_sources@1.1.0.yaml`), nên truy vấn về nội dung HSMT và tiêu chí
chấm điểm mới có cửa trả về đúng chủ đề.

**Chưa sửa, có chủ đích — chúng vẫn không rút ra con số nào.** Hai node đó không gọi
`verified_constraint()`, và đúng ra là không nên: chúng không sinh ra con số nào để kiểm.
Cái chúng sinh ra là văn bản, và văn bản không có hợp đồng chép-rồi-kiểm nào áp được.

### 8.6 Gate CP2 tra lại luật (25/08)

`package_gate` từng chặn bằng con số trong graph state — con số của lúc soạn. Hồ sơ nằm
giữa CP1 và CP2 hàng tuần, và `LawChangeScanner` quét 6 tiếng/lượt thì không kịp một hồ sơ
đi hết hai checkpoint trong một giờ.

Giờ nó hỏi lại đúng câu đã hỏi lúc soạn (`LEGAL_WINDOW_QUERY` — một hằng số, dùng chung
bởi node soạn, gate, và law watch), rồi `effective_legal_minimum()` (`rules.py`) hoà giải:

| Tình huống                           | Kết quả                                   |
| ------------------------------------ | ----------------------------------------- |
| Luật dài ra (18 → 25)                | Áp **25**, gate FAIL, lý do nêu cả hai số |
| Nguồn hôm nay nói ngắn hơn (25 → 18) | Vẫn **25** — chỉ siết, không nới          |
| Tra hỏng / không kiểm chứng được     | Giữ số đã soạn, **không** FAIL            |

Hàng cuối là hàng quan trọng nhất: `_cite()` nuốt lỗi và trả `[]`, nên một sự cố mạng phải
đi ra thành `None` chứ tuyệt đối không thành lý do chặn hồ sơ. Artifact
`SOLICITATION_PACKAGE` mang thêm `legal_recheck` ghi lại lúc trình CP2 đã đối chiếu với gì.

### 8.7 Danh mục mục bắt buộc — mới bóc, chưa cho chặn

`solicitation_gate` có sẵn nhánh "Thiếu mục bắt buộc" từ ngày viết nhưng `package_gate`
luôn truyền `missing_sections=[]`, nên nhánh đó **chưa từng chạy**. Đồng thời
`sections_present` là một list hardcode — nó _khẳng định_ chứ không _kiểm_.

`_extract_required_sections()` giờ bóc danh mục ấy ra từ chính trích đoạn, qua
`verified_sections()`: câu trích phải nằm nguyên văn trong một đoạn, và **mọi** tên mục
phải xuất hiện nguyên văn trong phần đã tra. Lỏng hơn `verified_constraint()` đúng một
điểm và có lý do — một con số là một khẳng định trong một câu, còn danh mục theo luật
thường trải qua nhiều khoản.

**Kết quả mới chỉ được ghi vào artifact và in lên thẻ CP2, chưa nối vào `missing_sections`.**
Neo `nội dung hồ sơ mời thầu` mới thêm hôm 24/08 và chưa chạy thật lần nào; nối một nguồn
chưa đo vào một cái gate đang chặn là cách nhanh nhất để cả đội học thói quen bỏ qua gate.
Chạy vài hồ sơ thật, đọc xem danh mục bóc ra có ổn định không, rồi mới nối.
