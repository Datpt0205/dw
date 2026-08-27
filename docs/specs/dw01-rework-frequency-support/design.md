# DW01 — Thiết kế kỹ thuật: theo dõi tần suất hồ sơ bị trả lại và hỗ trợ kịp thời

- **Trạng thái:** Draft
- **Ngày:** 2026-08-26
- **Nguồn yêu cầu:** [`requirements.md`](./requirements.md) — 73 yêu cầu `RF-01`…`RF-99`
- **Loại tài liệu:** Thiết kế kỹ thuật. Chốt module, lớp, bảng, endpoint. Không chốt nội dung câu chữ hiển thị (nằm ở §11).
- **Ràng buộc kiến trúc:** `CLAUDE.md`, `[tool.importlinter]` trong `pyproject.toml`

---

## 0. Nguyên tắc chi phối toàn bộ thiết kế

Bốn điều dưới đây quyết định mọi lựa chọn còn lại. Nếu một phương án nào mâu thuẫn với chúng thì phương án đó sai, kể cả khi nó gọn hơn.

**0.1 Trạng thái chặn là kết quả tính, không phải cột trạng thái.** Không có cột `is_blocked` nào được cập nhật tay. Mức hỗ trợ được suy ra từ các bản ghi lần trả lại mỗi khi cần (RF-8.6). Một cột trạng thái sẽ lệch khỏi sự thật ngay lần đầu ai đó chỉnh ngưỡng, và không ai biết nó đã lệch.

**0.2 Fail-open là mặc định, không phải nhánh xử lý lỗi.** Cơ chế này _chặn người dùng_. Một lỗi kết nối kho dữ liệu không được phép biến thành một lệnh cấm làm việc. Mọi đường vào đều bọc, và kết quả không tính được mang cờ riêng để phân biệt với "không có lần trả nào" (RF-98, RF-99).

**0.3 Lõi quyết định là hàm thuần.** Đếm và so ngưỡng không chạm I/O, không đọc đồng hồ hệ thống, nhận `now` từ tham số. Đây vừa là yêu cầu tất định (RF-15) vừa là điều kiện để test được biên ngưỡng mà không cần database.

**0.4 Ngôn từ là ràng buộc kỹ thuật.** Mọi chuỗi hiển thị đi qua đúng một module để test được ở một chỗ. Xem §11.

---

## 1. Bản đồ một trang

```
                        ┌─ điểm ghi (3 nơi, cùng giao dịch với đổi trạng thái) ─┐
                        │                                                      │
  RejectPreparationIntakeHandler ──┐                                           │
  apply_cp1  (node, nhánh từ chối)─┼──► record_rework_event(uow, …) ──► tender.preparation_rework_events
  apply_cp2  (node, nhánh từ chối)─┘         (application/rework_recording.py)         │
                                                                                      │
                                                                                      ▼
  configs/policies/dw01/rework_support_v1.yaml                              ReworkEventRepositoryPort
              │                                                             .list_for_creator(uid, since)
              ▼ load_rework_support_rules()                                           │
      ReworkSupportRules (frozen)                                                     │
              │                                                                       │
              └───────────────► assess_rework(events, now, rules) ◄────────────────────┘
                                (application/rework.py — HÀM THUẦN)
                                            │
                                            ▼
                                    ReworkAssessment
                        available · level(none|nudge|block) · counts
                        top_reason · guidance · policy_version
                                            │
                   ┌────────────────────────┼────────────────────────┐
                   ▼                        ▼                        ▼
            ReworkGuard              thẻ hỗ trợ trên UI        thông báo + leo thang
   (chặn create / run, fail-open)   (GET /rework/me)        (hàng đợi bền có sẵn)
                   │
                   └─ gỡ chặn ◄── DecideExplanationHandler ◄── SubmitExplanationHandler
                                  (SoD + required_role)          tender.preparation_explanations
```

---

## 2. Giả định chốt từ các câu hỏi mở

Bốn câu hỏi mở của `requirements.md` §13 được chốt như sau để triển khai được. Nếu bộ phận mua sắm quyết khác, chỉ phải sửa quy chế — trừ §13.5 đã ăn vào lược đồ.

| Câu hỏi                    | Chốt                                                                                     | Ảnh hưởng                       |
| -------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------- |
| §13.1 ngưỡng               | Nhắc 7 ngày/3 lần; chặn 30 ngày/5 lần                                                    | Chỉ trong quy chế               |
| §13.2 người hỗ trợ         | `procurement_head`                                                                       | Chỉ trong quy chế               |
| §13.3 hồi tố               | **Không hồi tố** — `enabled_from` trong quy chế, sự kiện trước mốc bị loại khỏi phép đếm | Một nhánh lọc trong hàm thuần   |
| §13.4 lưu trữ              | Vẫn để mở — không viết code xoá/lưu trữ                                                  | Không                           |
| §13.5 trả nhầm             | **Làm ngay** — ba cột `voided_*`, sự kiện bị đánh dấu không tính vào ngưỡng              | Ăn vào lược đồ và vào hàm thuần |
| §13.6 danh mục nguyên nhân | **Danh mục mới trong quy chế**, không tái dùng `Finding.code`                            | Quy chế + kiểm tra đầu vào      |

Về §13.6: `Finding.code` trong `readiness.py` (`no_package`, `criteria_weight`, `supplier_shortfall`…) sinh ra để mô tả _tình trạng hồ sơ do máy tự soát_, không phải _lý do một con người trả hồ sơ về_. Hai tập này giao nhau một phần nhưng không trùng, và ép dùng chung sẽ khiến người duyệt phải chọn một mã không mô tả đúng điều họ nghĩ. Danh mục riêng, ngắn, bảy mã.

---

## 3. Quy chế — `configs/policies/dw01/rework_support_v1.yaml`

Tách khỏi `procurement_rules_v1.yaml` chứ không nhét thêm vào đó. Ba lý do: khác vòng đời (ngưỡng hỗ trợ sẽ được hiệu chỉnh thường xuyên hơn ma trận thẩm quyền), khác người chỉnh, và cần `policy_version` riêng để RF-25 truy vết được một quyết định chặn về đúng bộ ngưỡng khi đó.

```yaml
schema_version: "1.0"
policy_id: dw01_rework_support
policy_version: "1.0.0"

enabled_from: "2026-08-26T00:00:00+00:00"

nudge: { window_days: 7, threshold: 3 }
block: { window_days: 30, threshold: 5 }

explanation:
    min_chars: 80
    supporter_role: procurement_head
    escalate_after_hours: 48

general_guidance: "…" # RF-34: dùng khi nhóm nguyên nhân không có gợi ý riêng

reason_codes: # RF-02 danh mục đóng; THỨ TỰ khai báo = thứ tự hoà điểm (RF-35)
    - { code: missing_pr_evidence, label: "…", guidance: "…" }
    - { code: budget_mismatch, label: "…", guidance: "…" }
    - { code: supplier_shortfall, label: "…", guidance: "…" }
    - { code: criteria_issue, label: "…", guidance: "…" }
    - { code: timeline_issue, label: "…", guidance: "…" }
    - { code: missing_documents, label: "…", guidance: "…" }
    - { code: other, label: "…", guidance: "…" }
```

**Tắt tính năng (RF-24):** đặt cả hai `threshold` về 0. Loader vẫn nạp, `is_enabled()` trả `False`, và mọi đường đều trả `SupportLevel.NONE` — không thẻ, không chặn, không thông báo.

Loader `adapters/preparation/rework_rules_loader.py::load_rework_support_rules(path)` theo đúng khuôn `load_procurement_rules`: từ chối `schema_version` lạ bằng `InfrastructureError` có kèm đường dẫn (RF-23).

---

## 4. Lõi thuần — `application/preparation/rework.py`

Không import SQLAlchemy, không import FastAPI, không gọi `datetime.now()`. Khuôn mẫu bám theo `repeat_purchase.py::find_repeat`.

### 4.1 Kiểu dữ liệu

```python
class SupportLevel(StrEnum):
    NONE = "none"; NUDGE = "nudge"; BLOCK = "block"

@dataclass(frozen=True, slots=True)
class ReworkReason:
    code: str; label: str; guidance: str

@dataclass(frozen=True)
class ReworkSupportRules:
    policy_version: str
    enabled_from: datetime | None
    nudge_window_days: int; nudge_threshold: int
    block_window_days: int; block_threshold: int
    explanation_min_chars: int
    supporter_role: str
    escalate_after_hours: int
    general_guidance: str
    reason_codes: tuple[ReworkReason, ...]     # thứ tự có ý nghĩa

    def is_enabled(self) -> bool
    def is_known(self, code: str) -> bool
    def reason(self, code: str) -> ReworkReason | None
    def guidance_for(self, code: str | None) -> str    # rơi về general_guidance

@dataclass(frozen=True, slots=True)
class ReworkEventView:
    """Đầu vào thuần của phép đếm — không phải thực thể lưu trữ."""
    event_id: uuid.UUID
    occurred_at: datetime
    reason_code: str
    checkpoint: str
    voided: bool = False

@dataclass(frozen=True)
class ReworkAssessment:
    available: bool                 # False = KHÔNG TÍNH ĐƯỢC (RF-99), khác hẳn count=0
    level: SupportLevel
    nudge_count: int; block_count: int
    nudge_window_days: int; block_window_days: int
    nudge_threshold: int; block_threshold: int
    top_reason_code: str | None
    top_reason_label: str
    guidance: str
    policy_version: str
    counted_event_ids: tuple[uuid.UUID, ...]   # RF-52: gắn vào bản giải trình

    @classmethod
    def unavailable(cls) -> ReworkAssessment     # fail-open (RF-98)
    @classmethod
    def disabled(cls, rules) -> ReworkAssessment # RF-24
```

### 4.2 Hàm quyết định

```python
def assess_rework(*, events, now, rules) -> ReworkAssessment
```

Trình tự, và lý do từng bước:

1. `rules.is_enabled()` sai → trả `disabled(...)` ngay. RF-24 nói tắt là tắt sạch.
2. Loại sự kiện có `voided=True`. §13.5 — một cú bấm nhầm không được nằm vĩnh viễn trong số đếm.
3. Loại sự kiện có `occurred_at < rules.enabled_from`. RF không hồi tố; nếu không có mốc thì không loại gì.
4. Đếm hai cửa sổ **độc lập** (RF-12): `nudge_count` trong `nudge_window_days` gần nhất, `block_count` trong `block_window_days`. Cửa sổ trượt tính ngược từ `now`, không phải tuần/tháng lịch (RF-11).
5. `block_count >= block_threshold` → `BLOCK`. Kiểm trước, nên khi cả hai cùng chạm thì chặn cứng thắng (RF-44).
6. `nudge_count >= nudge_threshold` → `NUDGE`.
7. Ngược lại `NONE`.
8. Nhóm nguyên nhân nổi trội: đếm trong **cửa sổ của mức đang áp dụng**. Hoà điểm giải bằng chỉ số khai báo trong quy chế, không `max()` trên dict (RF-35 — thứ tự lặp của dict là bẫy tất định kinh điển).
9. `guidance = rules.guidance_for(top_reason_code)`, tự rơi về `general_guidance` (RF-34).

Biên là `>=`, không phải `>`. "Đạt tới ngưỡng" trong RF-30/RF-40 nghĩa là bằng cũng tính. Test phải phủ cả `threshold - 1`, `threshold`, `threshold + 1`.

---

## 5. Domain — `domain/preparation/rework.py`

```python
class ReworkCheckpoint(StrEnum):
    INTAKE = "intake"; CP1 = "cp1"; CP2 = "cp2"

class ExplanationStatus(StrEnum):
    PENDING = "pending"; APPROVED = "approved"; REJECTED = "rejected"

@dataclass(frozen=True, slots=True)
class ReworkEvent:          # bất biến hoàn toàn ngoài ba cột void
    id, tenant_id, workspace_id, case_id, creator_user_id, decided_by_user_id,
    checkpoint, reason_code, reason_text, policy_version, occurred_at,
    voided_at=None, voided_by=None, void_reason=""
    @property
    def voided(self) -> bool

@dataclass(slots=True)
class ExplanationRecord:
    # nội dung bất biến; chỉ phần quyết định thay đổi được
    id, tenant_id, workspace_id, case_id, creator_user_id,
    context_text, difficulty_text, support_request_text,
    counted_event_ids, nudge_count, block_count, top_reason_code,
    policy_version, submitted_at,
    status=PENDING, decided_by=None, decided_at=None, decision_comment=""

    def decide(self, *, approve, decided_by, decided_at, comment) -> None
```

`ExplanationRecord.decide` cưỡng chế bốn điều, theo đúng khuôn `ApprovalRequest.decide` và `ApproveAndResumeService.decide`:

| Kiểm tra                | Yêu cầu | Lỗi             |
| ----------------------- | ------- | --------------- |
| Chưa có quyết định nào  | RF-66   | `ConflictError` |
| Người duyệt ≠ người nộp | RF-64   | `ConflictError` |
| `comment` không rỗng    | RF-63   | `ConflictError` |
| Nội dung không đổi      | RF-53   | không có setter |

Kiểm `required_role` (RF-61) nằm ở tầng application vì nó cần `context.roles`, thứ mà domain không được biết.

---

## 6. Persistence

### 6.1 Migration `0015_preparation_rework_support.py`

Hai bảng, schema `tender`, theo đúng khuôn `0011_dw01_slack_notifications.py`.

**`preparation_rework_events`**

| Cột                                     | Kiểu                                            | Ghi chú                        |
| --------------------------------------- | ----------------------------------------------- | ------------------------------ |
| `id`                                    | UUID PK                                         |                                |
| `tenant_id`, `workspace_id`             | UUID NOT NULL                                   | RF-8.1                         |
| `case_id`                               | UUID FK → `preparation_cases` ON DELETE CASCADE |                                |
| `creator_user_id`                       | UUID NOT NULL                                   | **khoá gom nhóm của phép đếm** |
| `decided_by_user_id`                    | UUID NOT NULL                                   | ai trả                         |
| `checkpoint`                            | Text + CHECK `IN ('intake','cp1','cp2')`        |                                |
| `reason_code`                           | Text NOT NULL                                   | RF-02                          |
| `reason_text`                           | Text NOT NULL                                   | RF-03, nguyên văn              |
| `policy_version`                        | Text NOT NULL                                   | RF-25                          |
| `occurred_at`                           | TIMESTAMPTZ NOT NULL                            | RF-8.3                         |
| `voided_at`, `voided_by`, `void_reason` | nullable / Text default `''`                    | §13.5                          |
| `created_at`                            | TIMESTAMPTZ default `now()`                     |                                |

Chỉ mục:

- `ix_prep_rework_creator_time (tenant_id, workspace_id, creator_user_id, occurred_at)` — chính xác truy vấn cửa sổ trượt, theo tiền lệ `ix_audit_events_tenant_time`.
- `ix_prep_rework_case (tenant_id, case_id, occurred_at)` — dựng lịch sử một hồ sơ.

**`preparation_explanations`** — `id`, `tenant_id`, `workspace_id`, `case_id`, `creator_user_id`, `context_text`, `difficulty_text`, `support_request_text`, `counted_event_ids` JSONB, `nudge_count`, `block_count`, `top_reason_code`, `policy_version`, `status` (CHECK `IN ('pending','approved','rejected')`), `decided_by`, `decided_at`, `decision_comment`, `submitted_at`, `created_at`.

Chỉ mục: `ix_prep_explanation_creator (tenant_id, workspace_id, creator_user_id, submitted_at)`; và một chỉ mục riêng phần `WHERE status = 'pending'` cho vòng quét leo thang (RF-73), theo tiền lệ `ix_outbox_events_unprocessed`.

**Bất biến cưỡng chế ở tầng DB.** Đây là phần đáng chú ý nhất của lược đồ. RF-07 và RF-53 cấm sửa nội dung, nhưng §13.5 và RF-62 lại cần sửa đúng vài cột. Giải bằng **grant theo cột** thay vì tin vào kỷ luật của tầng ứng dụng:

```sql
GRANT SELECT, INSERT ON tender.preparation_rework_events TO dw_app;
GRANT UPDATE (voided_at, voided_by, void_reason)
      ON tender.preparation_rework_events TO dw_app;

GRANT SELECT, INSERT ON tender.preparation_explanations TO dw_app;
GRANT UPDATE (status, decided_by, decided_at, decision_comment)
      ON tender.preparation_explanations TO dw_app;
```

Không cấp `DELETE` ở bất kỳ đâu — cùng lập trường với `REVOKE UPDATE, DELETE ON platform.audit_events` trong migration `0001`. Một lỗi lập trình cố sửa `reason_text` sẽ bị Postgres từ chối, không phải bị một code review bỏ sót.

RLS: `ENABLE` + `FORCE`, policy `tenant_isolation_<table>` dùng `NULLIF(current_setting('app.tenant_id', true), '')::uuid` như `0011`. Grants bọc trong `DO $$ IF EXISTS (SELECT FROM pg_roles WHERE rolname='dw_app')`.

### 6.2 Bảng đôi và repository

- `adapters/preparation/tables.py`: thêm hai `sa.Table`; đổi docstring thành _"Mirrors migrations 0007–0015 — change both together."_
- `adapters/preparation/rework_repositories.py` (file mới): `SqlReworkEventRepository`, `SqlExplanationRepository`. Tách file để `repositories.py` (đã 463 dòng) không phình thêm.
- `SqlPreparationUnitOfWork.__aenter__` dựng thêm `self.rework_events` và `self.explanations` trên cùng session — cần thiết cho RF-06.

### 6.3 Ports mới trong `application/preparation/ports.py`

```python
class ReworkEventRepositoryPort(Protocol):
    async def add(self, event: ReworkEvent) -> None: ...
    async def get(self, event_id: uuid.UUID) -> ReworkEvent | None: ...
    async def list_for_creator(self, creator_id: UserId, *, since: datetime) -> list[ReworkEvent]: ...
    async def void(self, event_id, *, voided_by, reason, at) -> None: ...

class ExplanationRepositoryPort(Protocol):
    async def add(self, record: ExplanationRecord) -> None: ...
    async def get(self, explanation_id) -> ExplanationRecord | None: ...
    async def save(self, record: ExplanationRecord) -> None: ...
    async def latest_pending_for_creator(self, creator_id: UserId) -> ExplanationRecord | None: ...
    async def list_pending_overdue(self, *, before: datetime) -> list[ExplanationRecord]: ...
```

`list_for_creator` nhận `since` chứ không nhận `days`: cắt cửa sổ là việc của lõi thuần, repository chỉ biết một mốc thời gian. Truyền `since = now - max(hai cửa sổ)` rồi để `assess_rework` cắt tiếp từng cửa sổ.

`tenant_id` và `workspace_id` **không** nằm trong chữ ký hàm nào (RF-81) — chúng đến từ ngữ cảnh đã xác thực, qua `set_config('app.tenant_id')` mà UoW đặt và RLS cưỡng chế.

---

## 7. Ghi sự kiện tại ba điểm trả lại

RF-06 buộc ghi sự kiện và đổi trạng thái hồ sơ nằm **cùng một giao dịch**. Hai trong ba điểm trả lại nằm bên trong node workflow đã có uow riêng. Nên phần ghi không thể là một handler tự mở uow — nó phải là hàm nhận sẵn `uow`:

```python
# application/preparation/rework_recording.py
async def record_rework_event(
    uow, *, case, decided_by, checkpoint, reason_code, reason_text,
    rules, clock, id_generator,
) -> None
```

Hàm này kiểm `rules.is_known(reason_code)` và raise `DomainError` nếu mã lạ (RF-05); kiểm `reason_text` không rỗng (RF-04); rồi `await uow.rework_events.add(...)`. Nó **không** gọi `commit` — khối gọi sở hữu giao dịch.

| Điểm   | Tệp                                                                           | Cách nối                                                                                                        |
| ------ | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Intake | `application/preparation/handlers.py` `RejectPreparationIntakeHandler.handle` | Thêm tham số `reason_code`; gọi bên trong khối `async with self.uow_factory(...)` đang có, trước `uow.commit()` |
| CP1    | `workflows/preparation_v1/nodes.py` `apply_cp1`                               | Nhánh `not approved`, trong khối uow đang có                                                                    |
| CP2    | `workflows/preparation_v1/nodes.py` `apply_cp2`                               | Nhánh `not approved`, trong khối uow đang có                                                                    |

### 7.1 Đường đi của `reason_code` cho CP1/CP2

CP1/CP2 bị trả qua `ApproveAndResumeService.decide` → `resume_payload` → node đọc từ `state["cp1_decision"]`. Hiện `resume_payload` chỉ mang `{"approved", "comment"}`. Cần nối thêm một trường:

1. `DecisionRequest` (`apps/api/src/dw_api/routes/v1/approvals.py`) thêm `reason_code: str = ""`.
2. `ApproveAndResumeService.decide` thêm tham số `reason_code: str = ""`, đưa vào `resume_payload` khi khác rỗng.
3. `apply_cp1` / `apply_cp2` đọc `decision.get("reason_code")`, rơi về `"other"` khi rỗng.

**Đánh dấu một lệch so với đặc tả.** RF-02 nói người duyệt _phải chọn_ một mã. Ở endpoint reject-intake điều này được cưỡng chế đầy đủ (trường bắt buộc). Ở CP1/CP2 thì mã là **tuỳ chọn, mặc định `other`** — vì bắt buộc ngay sẽ phá `DecisionRequest` của mọi client hiện có, gồm cả đường quyết định qua Slack/Zalo vốn không có chỗ chọn mã. Mã lạ vẫn bị từ chối (RF-05 giữ nguyên). Cần siết thành bắt buộc ở một phiên sau, khi các kênh chat đã có nút chọn mã. Ghi lại ở §13.

---

## 8. Chặn — `ReworkGuard`

```python
@dataclass
class ReworkGuard:
    uow_factory: PreparationUnitOfWorkFactory
    rules: ReworkSupportRules
    clock: UtcClock

    async def assess(self, context) -> ReworkAssessment      # không bao giờ raise
    async def require_not_blocked(self, context) -> None     # raise ConflictError khi BLOCK
```

`assess` bọc toàn bộ thân hàm trong `try/except Exception`, log cảnh báo, trả `ReworkAssessment.unavailable()`. Đây là RF-98 và là điều quan trọng nhất trong lớp này: **một cơ chế chặn người dùng không được phép chặn vì hạ tầng lỗi.**

Điểm cắm, đúng theo RF-41:

| Handler                               | Chặn gì                    | RF    |
| ------------------------------------- | -------------------------- | ----- |
| `CreatePreparationCaseHandler.handle` | Tạo hồ sơ mới              | RF-41 |
| `RunPreparationHandler.handle`        | Trình hồ sơ lên checkpoint | RF-41 |

Không cắm vào các đường sửa/lưu hồ sơ đang dở, cũng không vào `AmendPreparationCaseHandler` — RF-42 nói rõ người bị chặn vẫn phải sửa được việc đang làm dở. Chặn cả đường sửa sẽ biến cơ chế hỗ trợ thành cái bẫy: người dùng bị bảo "hãy sửa" mà không sửa được.

Guard nhận `rules` qua hàm khởi tạo (constructor injection), không đọc file lúc chạy.

---

## 9. Handlers — `application/preparation/rework_handlers.py`

| Handler                      | Trách nhiệm                                                                                                                | Yêu cầu                |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| `AssessReworkSupportHandler` | Đọc, trả `ReworkAssessment` cho người gọi hiện tại                                                                         | RF-92, RF-98           |
| `SubmitExplanationHandler`   | Kiểm độ dài tối thiểu, chụp `counted_event_ids` tại đúng thời điểm nộp, ghi bản ghi, tạo yêu cầu duyệt, xếp hàng thông báo | RF-50…57, RF-60, RF-70 |
| `DecideExplanationHandler`   | `authorization.require` → kiểm `required_role` ∈ `context.roles` → `record.decide(...)` → audit                            | RF-61…66               |
| `VoidReworkEventHandler`     | Đánh dấu trả nhầm, bắt buộc lý do, audit                                                                                   | §13.5, RF-84           |

`SubmitExplanationHandler` gọi `assess_rework` **trước** khi ghi và lưu `counted_event_ids` từ kết quả đó. Đây là điểm tinh tế của RF-52: bản giải trình phải gắn với đúng tập sự kiện đã đẩy người dùng qua ngưỡng _tại thời điểm nộp_, không phải tập sự kiện lúc ai đó mở lại nó ba tuần sau — lúc ấy cửa sổ đã trôi và tập đã khác.

Phân quyền: `authorization.require(action="approvals.decide", ...)` cho các thao tác quyết định, `"tender.write"` cho việc nộp (RF-82). Kiểm quyền và kiểm thẩm quyền là hai bước tách rời (RF-83).

---

## 10. Thông báo

Ba loại sự kiện mới trên `IntakeNotificationType`:

| Giá trị                        | Người nhận                         | Khi nào                                                |
| ------------------------------ | ---------------------------------- | ------------------------------------------------------ |
| `rework.support_offered`       | Người tạo                          | Chuyển vào chặn mềm (RF-30)                            |
| `rework.support_required`      | Người hỗ trợ theo `supporter_role` | Chuyển vào chặn cứng (RF-70)                           |
| `rework.explanation_escalated` | `platform_admin`                   | Bản giải trình treo quá `escalate_after_hours` (RF-73) |

Bốn ràng buộc kèm theo, mỗi cái đều là một cái bẫy đã biết trong repo này:

1. **`_reply_hint` trong `zalo_approval_notifier.py` trả chuỗi rỗng cho event type lạ.** Thêm loại mới mà quên thêm nhánh thì thẻ Zalo mất lời gọi hành động và không ai báo lỗi. Ba nhánh mới là bắt buộc, có test (RF-75).
2. **Logic huỷ thẻ cũ trong `apps/worker/.../consumers/slack_approvals.py`** so `delivery.case_state` với trạng thái mong đợi để huỷ thẻ lỗi thời. Sự kiện mới gắn với _người dùng_, không với trạng thái hồ sơ, nên phải được loại khỏi phép so đó — nếu không thẻ sẽ bị huỷ ngay khi hồ sơ đổi trạng thái.
3. **Khoá chống trùng** theo khuôn `dw01:{case_id}:{event}:{dedupe}` đang dùng, với `dedupe` là mức hỗ trợ cộng số đếm — cùng một mức, cùng số lần thì không sinh thẻ mới (RF-72, RF-36).
4. **Người nhận** qua `find_recipient_for_role(supporter_role, exclude=case.created_by)` (RF-74).

Xếp hàng thông báo nằm trong cùng giao dịch với việc ghi, theo đúng cách `_notify_progress` đang làm; gửi là việc của worker, hỏng thì thử lại và không làm hỏng giao dịch nghiệp vụ (RF-76).

---

## 11. Ngôn từ — module dựng câu duy nhất

`application/preparation/rework_wording.py` là **nơi duy nhất** sinh chuỗi hiển thị. Không f-string nào hướng người dùng nằm rải rác trong handler, node, hay route.

```python
FORBIDDEN = ("vi phạm", "sai phạm", "lách", "chia nhỏ")   # RF-91

def support_headline(assessment) -> str
def support_lines(assessment) -> list[str]
def explanation_prompt(assessment) -> str
def supporter_lines(assessment, *, creator_label) -> list[str]
def blocked_message(assessment) -> str
```

Giọng: hỏi bối cảnh và đề nghị hỗ trợ, không quy kết (RF-90). Nói về _hồ sơ_, không về _người_. Ví dụ hình dáng câu — `"Mấy hồ sơ gần đây phải chỉnh lại {n} lần trong {d} ngày. Thường là do {label} — {guidance}. Bạn mô tả giúp bối cảnh để bên mua sắm hỗ trợ nhé."`

Gom một chỗ để test được một chỗ: `test_rework_wording.py` gọi mọi hàm ở trên với đủ tổ hợp mức và nhóm nguyên nhân, khẳng định không chuỗi nào chứa từ trong `FORBIDDEN`. Đây là bản mở rộng của `test_repeat_purchase.py:77`, không phải một chuẩn mới.

---

## 12. API, DTO, client, UI

### 12.1 Endpoint mới trên `build_preparation_router`

| Method | Đường dẫn                                                    | Trả về              | RF    |
| ------ | ------------------------------------------------------------ | ------------------- | ----- |
| `GET`  | `/procurement/preparation/rework/me`                         | `ReworkSupportView` | RF-92 |
| `POST` | `/procurement/preparation/rework/explanations`               | `{explanation_id}`  | RF-50 |
| `POST` | `/procurement/preparation/rework/explanations/{id}/decision` | `ActionResponse`    | RF-62 |
| `POST` | `/procurement/preparation/rework/events/{id}/void`           | `ActionResponse`    | §13.5 |

Endpoint `reject-intake` hiện có thêm trường **bắt buộc** `reason_code` trên `RejectIntakeRequest`.

Mọi request model dùng `model_config = ConfigDict(extra="forbid")` như phần còn lại của file. Lỗi ném ra dạng domain error, để `exception_handlers.py` ánh xạ tập trung.

### 12.2 DTO

`PreparationCaseView` thêm `rework_support: ReworkSupportView | None`. Để `None` khi tính năng tắt hoặc không tính được — phía UI phân biệt được và không vẽ thẻ.

### 12.3 Client và UI

- `packages/typescript/api-client/src/client.ts`: zod schema `reworkSupportSchema` + bốn method tương ứng.
- `apps/web/app/procurement/dw01/cases/[caseId]/page.tsx`: thẻ hỗ trợ và form giải trình, tái dùng đúng khuôn `clarificationItems` — khoá nút nộp khi mức là `block` và form chưa đủ độ dài tối thiểu.
- `contracts/openapi/openapi.json` phải sinh lại (`make generate-contracts`), nếu không `test_openapi_snapshot.py` sẽ đỏ.

**RF-47 nhắc lại ở đây vì nó dễ bị quên ở tầng UI:** ẩn nút không phải là biện pháp phân quyền. Guard ở máy chủ là thứ chặn thật; UI chỉ để người dùng khỏi bấm vào chỗ chắc chắn hỏng.

---

## 13. Lệch so với đặc tả, và nợ kỹ thuật

| #   | Nội dung                                                                                          | Lý do                                                                                                       | Hành động                                     |
| --- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| D-1 | `reason_code` ở CP1/CP2 là tuỳ chọn, mặc định `other` — RF-02 nói bắt buộc                        | Bắt buộc ngay sẽ phá mọi client hiện có và đường quyết định qua chat vốn không có chỗ chọn mã               | Siết ở phiên sau khi kênh chat có nút chọn mã |
| D-2 | RF-96 phát chỉ số: nhãn ở mức tenant và nhóm nguyên nhân, tuyệt đối không có định danh người dùng | RF-95 và ràng buộc nhãn lực lượng thấp của `metrics.py`                                                     | Đã tính trong thiết kế                        |
| N-1 | `scripts/release_manifest.py::_policies()` chỉ quét `configs/policies/*.yaml` cấp cao nhất        | Quy chế mới nằm trong `dw01/` nên sẽ **không** vào release manifest, làm RF-25 không truy vết được đến cùng | Phải sửa trong cùng đợt này                   |

---

## 14. Ma trận yêu cầu → nơi thực thi

| Nhóm                  | RF       | Nơi thực thi                                                                                     |
| --------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| Ghi sự kiện           | RF-01…08 | `rework_recording.py`; 3 điểm gọi ở `handlers.py` và `nodes.py`; migration 0015 (grant theo cột) |
| Đếm cửa sổ trượt      | RF-10…16 | `application/preparation/rework.py::assess_rework`                                               |
| Ngưỡng và cấu hình    | RF-20…25 | `rework_support_v1.yaml`, `rework_rules_loader.py`, `ReworkSupportRules`                         |
| Chặn mềm              | RF-30…36 | `assess_rework`, `rework_wording.py`, DTO, UI                                                    |
| Chặn cứng             | RF-40…47 | `ReworkGuard`, cắm vào `CreatePreparationCaseHandler` và `RunPreparationHandler`                 |
| Bản giải trình        | RF-50…57 | `ExplanationRecord`, `SubmitExplanationHandler`, migration 0015                                  |
| Duyệt và gỡ chặn      | RF-60…66 | `ExplanationRecord.decide`, `DecideExplanationHandler`                                           |
| Thông báo             | RF-70…76 | `IntakeNotificationType`, `zalo_approval_notifier.py`, `slack_approvals.py`                      |
| Đa tenant, phân quyền | RF-80…84 | RLS trong migration 0015; UoW `set_config`; `authorization.require` ở handler                    |
| Ngôn từ               | RF-90…95 | `rework_wording.py` + `test_rework_wording.py`                                                   |
| Quan sát              | RF-96…99 | `ReworkGuard` fail-open; `ReworkAssessment.available`; chỉ số ở `metrics.py`                     |
