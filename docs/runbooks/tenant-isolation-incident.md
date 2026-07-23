# Runbook — Nghi ngờ rò rỉ dữ liệu giữa tenant

Mức độ: SEV-1. Cô lập trước, phân tích sau.

## Bước 1 — Cô lập (≤ 15 phút)

1. Tắt API public: `docker compose ... stop api worker` (web có thể giữ để hiển thị maintenance).
2. KHÔNG xoá gì cả — audit và WAL là bằng chứng.

## Bước 2 — Xác minh giả thuyết

Chạy lại bộ test cách ly trên môi trường staging giống production:

```bash
uv run pytest -m integration -k "isolation or cross_tenant" -q
uv run python scripts/run_evals.py --dataset "evals/datasets/tender@1.0.0.json"
```

Ba lớp phải cùng pass:

- SQL: RLS `ENABLE+FORCE`, role app `NOBYPASSRLS` —
  `SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relnamespace = 'platform'::regnamespace;`
- API: cross-tenant đọc → 404, không phải 403-with-existence-leak.
- Qdrant: search đúng nguyên văn nội dung tenant khác phải trả 0 kết quả.

## Bước 3 — Truy vết

1. `platform.audit_events` theo `trace_id`/`actor_id` trong khoảng thời gian nghi ngờ
   (bảng append-only — dw_app không sửa/xoá được).
2. Đối chiếu `worker_runs.release_manifest_ref` để biết chính xác phiên bản
   graph/prompt/policy nào đã chạy.
3. Kiểm tra có kết nối DB nào dùng role bypass RLS ngoài migration job:
   `SELECT rolname, rolbypassrls FROM pg_roles;`

## Bước 4 — Khắc phục phổ biến

| Lỗ hổng                             | Fix                                                                                                                 |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Bảng mới thiếu RLS policy           | Thêm migration ENABLE+FORCE + policy `tenant_id = current_setting('app.tenant_id', true)::uuid`; thêm negative test |
| Query dùng session không set tenant | Mọi truy cập phải qua UoW/session helper có `_SET_TENANT`; grep `session_factory()` mới thêm                        |
| Qdrant filter dựng ngoài gateway    | Chỉ `build_trusted_filter()` được phép; thêm import-linter/test nếu tái phạm                                        |

## Bước 5 — Hậu kiểm

Bổ sung case tấn công tương ứng vào `evals/datasets/*` (category
`cross_tenant_attack`) để CI chặn vĩnh viễn, rồi mới mở lại API.
