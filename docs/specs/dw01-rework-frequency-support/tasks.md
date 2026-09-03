# DW01 — Danh sách công việc: theo dõi tần suất hồ sơ bị trả lại và hỗ trợ kịp thời

- **Trạng thái:** Đang triển khai
- **Ngày:** 2026-08-26
- **Nguồn:** [`requirements.md`](./requirements.md) · [`design.md`](./design.md)

Mười giai đoạn, xếp theo thứ tự **giảm rủi ro trước, tăng bề mặt sau**: logic nghiệp vụ duyệt được trước khi đụng database, database xong trước khi đụng API, API xong trước khi đụng UI. Mỗi giai đoạn kết thúc bằng một thứ chạy được.

---

## T1 — Quy chế và lõi thuần

- [x] `configs/policies/dw01/rework_support_v1.yaml` — hai cửa sổ, hai ngưỡng, `enabled_from`, `explanation`, `general_guidance`, bảy `reason_codes` có nhãn tiếng Việt và gợi ý hỗ trợ
- [x] `application/preparation/rework.py` — `SupportLevel`, `ReworkReason`, `ReworkSupportRules`, `ReworkEventView`, `ReworkAssessment`, `assess_rework(...)`
- [x] `adapters/preparation/rework_rules_loader.py` — `load_rework_support_rules(path)`, từ chối `schema_version` lạ bằng `InfrastructureError` kèm đường dẫn
- [x] `application/preparation/rework_wording.py` — `FORBIDDEN` + các hàm dựng câu

**Xong khi:** import được, `assess_rework` chạy trên dữ liệu dựng tay.

---

## T2 — Unit test lõi (trước khi đụng database)

- [x] `test_rework_support.py` — biên `threshold-1 / threshold / threshold+1`; hai cửa sổ độc lập; chặn cứng thắng khi cả hai chạm; loại sự kiện `voided`; loại sự kiện trước `enabled_from`; ngưỡng 0 tắt sạch; hoà điểm nhóm nguyên nhân theo thứ tự khai báo; tất định khi chạy hai lần; `unavailable` khác `count=0`
- [x] `test_rework_rules_loader.py` — nạp file thật; thiếu trường; sai kiểu; `schema_version` lạ; ngưỡng 0
- [x] `test_rework_wording.py` — mọi hàm dựng câu, mọi mức, mọi nhóm nguyên nhân, không chuỗi nào chứa từ cấm

**Xong khi:** `uv run pytest packages/python/dw_tender/tests/unit/test_rework_*.py -q` xanh.

---

## T3 — Domain, ports, persistence

- [x] `domain/preparation/rework.py` — `ReworkCheckpoint`, `ExplanationStatus`, `ReworkEvent`, `ExplanationRecord.decide(...)`
- [x] `test_rework_explanation.py` — quyết định hai lần; tự duyệt bản của mình; nhận xét rỗng
- [x] `db/migrations/versions/0015_preparation_rework_support.py` — hai bảng, CHECK, chỉ mục cửa sổ, RLS `ENABLE`+`FORCE`, grant **theo cột**, không `DELETE`
- [x] `adapters/preparation/tables.py` — hai `sa.Table`, cập nhật docstring
- [x] `application/preparation/ports.py` — `ReworkEventRepositoryPort`, `ExplanationRepositoryPort`, thêm vào `PreparationUnitOfWork`
- [x] `adapters/preparation/rework_repositories.py` — `SqlReworkEventRepository`, `SqlExplanationRepository`
- [x] `adapters/preparation/repositories.py` — nối hai repository vào `SqlPreparationUnitOfWork.__aenter__`

**Xong khi:** `make migrate` lên và xuống được trên DB trống.

---

## T4 — Ghi sự kiện tại ba điểm trả lại

- [x] `application/preparation/rework_recording.py` — `record_rework_event(uow, ...)`, không tự `commit`
- [x] `RejectPreparationIntakeHandler.handle` — thêm `reason_code`, gọi trong khối uow đang có
- [x] `nodes.py` `apply_cp1` — nhánh từ chối
- [x] `nodes.py` `apply_cp2` — nhánh từ chối
- [x] `approval_flow.py` + `routes/v1/approvals.py` — nối `reason_code` qua `resume_payload`
- [x] Audit action mới: `preparation.rework.recorded`, `preparation.rework.voided`, `preparation.explanation.submitted`, `preparation.explanation.decided`

**Xong khi:** trả một hồ sơ ở mỗi chốt đều sinh đúng một bản ghi, cùng giao dịch.

---

## T5 — Chặn, handlers, wiring

- [x] `ReworkGuard` — `assess` không bao giờ raise, `require_not_blocked` raise `ConflictError`
- [x] `application/preparation/rework_handlers.py` — `AssessReworkSupportHandler`, `SubmitExplanationHandler`, `DecideExplanationHandler`, `VoidReworkEventHandler`
- [x] Cắm guard vào `CreatePreparationCaseHandler.handle` và `RunPreparationHandler.handle`
- [x] `apps/api/src/dw_api/bootstrap.py` — nạp quy chế, dựng guard và handlers, thêm vào `PreparationHandlers`

**Xong khi:** vượt ngưỡng chặn thì tạo hồ sơ mới bị từ chối; duyệt giải trình thì gỡ.

---

## T6 — Thông báo

- [x] `IntakeNotificationType` — ba giá trị mới
- [x] `zalo_approval_notifier.py` `_reply_hint` — ba nhánh mới
- [x] `consumers/slack_approvals.py` — loại sự kiện mới khỏi phép so `case_state` để không bị huỷ nhầm
- [x] Khoá chống trùng theo mức và số đếm
- [x] Test nhánh `_reply_hint` không rơi vào chuỗi rỗng

---

## T7 — API, DTO, hợp đồng

- [x] `dto.py` — `ReworkSupportView`, thêm vào `PreparationCaseView`
- [x] `preparation_api.py` — bốn endpoint mới; `RejectIntakeRequest.reason_code` bắt buộc
- [x] `main.py` — truyền handlers mới vào `build_preparation_router`
- [x] Sinh lại `contracts/openapi/openapi.json`
- [x] `packages/typescript/api-client/src/client.ts` — zod schema + bốn method

---

## T8 — Giao diện

- [x] Thẻ hỗ trợ trên trang hồ sơ — số lần, cửa sổ, nhóm nguyên nhân, gợi ý
- [x] Form giải trình — ba ô, khoá nút nộp khi chưa đủ độ dài tối thiểu
- [x] Trạng thái chặn cứng hiển thị rõ cách gỡ

---

## T9 — Trả nợ kỹ thuật

- [x] `scripts/release_manifest.py::_policies()` — quét cả thư mục lồng để quy chế `dw01/` vào được release manifest

---

## T10 — Cổng chất lượng

- [x] `make lint`
- [x] `make typecheck`
- [x] `make test-unit`
- [x] `make test-architecture`
- [ ] `make test-integration` — **không chạy được**: container Postgres không publish port, `dw_migrator` không xác thực được từ host. Đã thay bằng kiểm chứng tương đương ở §Ghi chú bên dưới
- [x] Kiểm ngôn từ: `grep -rniE 'vi phạm|sai phạm|lách|chia nhỏ'` trên tệp mới
- [x] Đối chiếu ngược `requirements.md`: mỗi `RF-` có nơi thực thi hoặc được ghi là lệch ở `design.md` §13

---

## Ghi chú khi triển khai

**Migration đã kiểm chứng bằng cách khác.** `make migrate` không chạy được từ host: container
`dw-postgres-1` không publish port nào, nên `localhost:5432` trỏ tới một Postgres khác. Thay vào
đó đã render toàn bộ chuỗi bằng `alembic upgrade head --sql` rồi nạp vào một database nháp bên
trong container. Kết quả: 0001→0015 chạy sạch trên nền trống, `alembic_version` = 0015, hai bảng
có RLS bật, đủ 4 chỉ mục và 5 check constraint.

**Tính bất biến đã được chứng minh, không chỉ khai báo.** Chạy thật với vai trò `dw_app`:

| Thao tác                                 | Kết quả                                             |
| ---------------------------------------- | --------------------------------------------------- |
| `UPDATE ... SET reason_text`             | `ERROR: permission denied`                          |
| `DELETE FROM preparation_rework_events`  | `ERROR: permission denied`                          |
| `UPDATE ... SET voided_at, void_reason`  | `UPDATE 1`                                          |
| `SELECT` dưới tenant khác                | 0 dòng                                              |
| `INSERT` với `tenant_id` của tenant khác | `ERROR: new row violates row-level security policy` |

Database dev **không bị đụng tới** — vẫn ở 0014. Chạy `make migrate` là quyết định của người vận hành.

**Một lỗi có sẵn, không do đợt này.** `make test-unit` đỏ ở
`test_slack_settings_require_all_demo_member_mappings`. Nguyên nhân: Makefile `include .env; export`,
và `.env` cục bộ đặt `DW_APPROVAL_CHANNEL=zalo`, khiến `validate_slack()` rẽ nhánh zalo và return
sớm. Đã kiểm chứng lỗi này tồn tại trên bản gốc trước mọi thay đổi. `uv run pytest -m unit` xanh
toàn bộ.

**Hai loại thẻ Zalo có sẵn cũng rơi vào mặc định rỗng.** `intake.approved` và `intake.rejected`
không có lời gọi hành động. Đã ghi vào `test_zalo_reply_hints.py` như hiện trạng, không sửa —
thẻ trả hồ sơ đáng có một bước tiếp theo, nhưng đó là quyết định riêng về một luồng đang chạy.
