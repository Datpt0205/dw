# Runbook — Run kẹt ở waiting_approval

## Triệu chứng

Run ở `waiting_approval` lâu; approval inbox không thấy hoặc approve xong run
không chạy tiếp.

## Chẩn đoán

1. Xem run + approval id:
   `GET /api/v1/runs/{run_id}` → `approval_request_id`, `release_manifest_ref`.
2. Xem timeline: `GET /api/v1/runs/{run_id}/timeline` — chuỗi đúng phải là
   `run.started → run.waiting_approval` (chưa có `run.resumed`).
3. Kiểm tra approval:
   `SELECT status, version FROM platform.approval_requests WHERE id = ...`
   (psql bằng role `dw_migrator`, nhớ đây là thao tác vận hành có audit riêng).

## Các nguyên nhân thường gặp

| Hiện tượng                        | Nguyên nhân                                                | Xử lý                                                                                                                           |
| --------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Approve trả 403                   | User thiếu scope `approvals.decide` (role member không có) | Đăng nhập bằng user approver (`binh.tran` trong seed)                                                                           |
| Approve trả 409 conflict          | Approval đã được quyết định trước đó (decide-once)         | Đọc `decided_at`/`decision`; không quyết định lại được — đúng thiết kế                                                          |
| Approve 200 nhưng run vẫn waiting | Resume ném lỗi sau khi decision ghi xong                   | Xem log API; checkpoint vẫn còn trong `platform.run_checkpoints` — sửa nguyên nhân rồi gọi lại resume qua approval flow phụ trợ |
| Run biến mất sau restart          | Không thể — state nằm toàn bộ trong Postgres               | Nếu thật sự mất: kiểm tra đang trỏ đúng database                                                                                |

## Kiểm chứng resume durable

Integration test `test_checkpoint_resume` dựng lại toàn bộ runner stack giữa
pause và resume; nếu nghi ngờ regression chạy:

```bash
uv run pytest packages/python/dw_agent_runtime/tests/integration -q
```
