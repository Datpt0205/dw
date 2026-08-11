#!/usr/bin/env bash
# =============================================================================
# DW01 demo: thêm vài hồ sơ "hàng xóm" để bức tranh toàn cảnh không trống trơn.
#
# Khi Chi (trưởng ban) hỏi "tình hình chung thế nào?", một hồ sơ duy nhất không
# cho thấy gì. Script này dựng thêm 4 hồ sơ ở các giai đoạn khác nhau, do NGƯỜI
# KHÁC đề nghị, để câu trả lời có nhóm "chờ bạn quyết / đang chạy / hoàn tất".
#
# HAI hồ sơ cùng nằm ở CP2 là cố ý: đó là ca thử "Chi chỉ nói «duyệt»" — hệ
# thống phải hỏi lại chứ không được tự chọn.
#
# created_by = Bình (không phải An) nên:
#   - Chi và Bình (có approvals.decide) thấy cả 5 hồ sơ;
#   - An chỉ thấy đúng hồ sơ của mình — giữ nguyên đối chứng về phạm vi xem;
#   - Chi duyệt được, vì SoD chỉ chặn chính người tạo.
#
# Idempotent: id cố định, chạy lại bao nhiêu lần cũng ra đúng 4 hồ sơ đó.
# Xoá: bash scripts/demo_reset.sh (dọn sạch mọi hồ sơ).
#
# Usage:  bash scripts/seed_demo_cases.sh     (từ repo root, stack đang chạy)
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

PGU=$(grep '^POSTGRES_USER=' .env | cut -d= -f2)
COMPOSE="docker compose --env-file .env -f infra/compose/docker-compose.yml"

$COMPOSE exec -T postgres psql -U "$PGU" -d dw -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;

-- Alpha tenant/workspace + Bình là người tạo (xem đầu file).
\set tenant   '''d6b43d0e-c3c6-5dbc-bc08-150621bd9a5d'''
\set ws       '''64764894-718d-5558-ba17-9a2949214063'''
\set binh     '''d03b556c-dd77-5fd8-ba37-58d0b50d42d3'''

DELETE FROM platform.approval_requests
 WHERE id IN ('a0000000-0000-4000-8000-000000000001',
              'a0000000-0000-4000-8000-000000000002');
DELETE FROM tender.preparation_cases
 WHERE id IN ('c0000000-0000-4000-8000-000000000001',
              'c0000000-0000-4000-8000-000000000002',
              'c0000000-0000-4000-8000-000000000003',
              'c0000000-0000-4000-8000-000000000004');

INSERT INTO tender.preparation_cases
  (id, tenant_id, workspace_id, title, description, source_pr_ref,
   estimated_value_minor, currency, deadline, owner_name, method_key, state,
   current_step, created_by, version, created_at, updated_at,
   procurement_type, business_domain)
VALUES
  -- (1) chờ Chi quyết — CP2
  ('c0000000-0000-4000-8000-000000000001', :tenant, :ws,
   'Mua 300 màn hình 27 inch cho khối văn phòng',
   'Thay thế màn hình đã hết khấu hao tại 3 chi nhánh.',
   'PR-2026-0311', 12000000000, 'VND', '60 ngày', 'Phạm Minh Đức',
   'open_tender', 'cp2_pending', 'cp2_review', :binh, 6,
   now() - interval '9 days', now() - interval '1 day', 'goods', 'general'),

  -- (2) cũng chờ Chi quyết — CP2. Trùng checkpoint với (1) là CỐ Ý.
  ('c0000000-0000-4000-8000-000000000002', :tenant, :ws,
   'Thuê dịch vụ bảo trì hệ thống điện năm 2026',
   'Bảo trì định kỳ hệ thống điện toàn nhà máy.',
   'PR-2026-0298', 8400000000, 'VND', '45 ngày', 'Lê Thu Hà',
   'open_tender', 'cp2_pending', 'cp2_review', :binh, 6,
   now() - interval '7 days', now() - interval '2 days', 'non_consulting', 'operations'),

  -- (3) đang chạy — đã phát hành, chờ nhà cung cấp nộp
  ('c0000000-0000-4000-8000-000000000003', :tenant, :ws,
   'Mua 50 máy in đa năng cho các phòng ban',
   'Bổ sung máy in cho khối kinh doanh và kế toán.',
   'PR-2026-0275', 2500000000, 'VND', '30 ngày', 'Vũ Quốc Toản',
   'rfq', 'published', 'published', :binh, 11,
   now() - interval '14 days', now() - interval '3 days', 'goods', 'information_technology'),

  -- (4) hoàn tất
  ('c0000000-0000-4000-8000-000000000004', :tenant, :ws,
   'Mua vật tư văn phòng quý 2/2026',
   'Giấy, mực in, văn phòng phẩm dùng chung.',
   'PR-2026-0190', 780000000, 'VND', '20 ngày', 'Ngô Thanh Tùng',
   'rfq', 'completed', 'completed', :binh, 17,
   now() - interval '38 days', now() - interval '11 days', 'goods', 'general');

-- Hai hồ sơ CP2 phải có approval_request thì mới nằm trong danh sách "chờ
-- quyết định" mà lệnh «duyệt» đọc. requested_by = Bình để Chi duyệt được.
INSERT INTO platform.approval_requests
  (id, tenant_id, workspace_id, approval_type, requested_by, reason, payload,
   run_id, status, created_at, version)
VALUES
  ('a0000000-0000-4000-8000-000000000001', :tenant, :ws,
   'preparation.cp2', :binh, 'Duyệt bộ hồ sơ mời thầu chính thức',
   '{"case_id":"c0000000-0000-4000-8000-000000000001","case_title":"Mua 300 màn hình 27 inch cho khối văn phòng"}'::jsonb,
   NULL, 'pending', now() - interval '1 day', 1),
  ('a0000000-0000-4000-8000-000000000002', :tenant, :ws,
   'preparation.cp2', :binh, 'Duyệt bộ hồ sơ mời thầu chính thức',
   '{"case_id":"c0000000-0000-4000-8000-000000000002","case_title":"Thuê dịch vụ bảo trì hệ thống điện năm 2026"}'::jsonb,
   NULL, 'pending', now() - interval '2 days', 1);

COMMIT;
SQL

echo "Hồ sơ hiện có:"
$COMPOSE exec -T postgres psql -U "$PGU" -d dw -tAc \
  "select '  '||rpad(state,16)||' | '||rpad(owner_name,18)||' | '||title
     from tender.preparation_cases order by created_at"
echo "Đang chờ quyết định:"
$COMPOSE exec -T postgres psql -U "$PGU" -d dw -tAc \
  "select '  '||approval_type||' | '||(payload->>'case_title')
     from platform.approval_requests where status='pending' order by created_at"
