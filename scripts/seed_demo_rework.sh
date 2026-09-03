#!/usr/bin/env bash
# =============================================================================
# DW01 demo: dựng sẵn lịch sử "hồ sơ bị trả lại" cho An.
#
# Ngưỡng chặn cứng là 5 lần trong 30 ngày (configs/policies/dw01/
# rework_support_v1.yaml). Diễn thật 5 lần trả hồ sơ mất khoảng 6 phút và
# chẳng cho thấy điều gì — cái đáng quay là chuyện xảy ra SAU khi chạm ngưỡng.
# Nên gieo phần lịch sử, diễn phần còn lại.
#
# Số liệu gieo ở đây là thật theo mọi nghĩa hệ thống quan tâm: cùng bảng, cùng
# ràng buộc, cùng RLS. Không có đường tắt nào bỏ qua phép đếm.
#
# CHẠY KHI NÀO: chỉ trước cảnh 10-11, KHÔNG chạy trước cảnh 1.
# Chạy sớm thì An bị chặn ngay câu mở đầu và cả mạch diễn hỏng.
#
#   bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh   # cảnh 1-9
#   ... quay tới hết cảnh 9 ...
#   bash scripts/seed_demo_rework.sh                                 # cảnh 10-11
#
# Gỡ ra: bash scripts/seed_demo_rework.sh --clear
# Idempotent: id cố định, chạy lại vẫn đúng 5 bản ghi.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

PGU=$(grep '^POSTGRES_USER=' .env | cut -d= -f2)
COMPOSE="docker compose --env-file .env -f infra/compose/docker-compose.yml"

if [[ "${1:-}" == "--clear" ]]; then
  $COMPOSE exec -T postgres psql -U "$PGU" -d dw -v ON_ERROR_STOP=1 <<'SQL'
DELETE FROM tender.preparation_explanations;
DELETE FROM tender.preparation_rework_events;
SQL
  echo "✔ Đã gỡ lịch sử trả hồ sơ — An làm việc bình thường trở lại."
  exit 0
fi

# --- Chốt chặn: mốc không-hồi-tố có nuốt mất dữ liệu gieo không? -------------
# Cái bẫy đã vấp một lần: enabled_from đặt đúng ngày hôm nay thì MỌI bản ghi
# gieo (đều ở quá khứ) bị loại khỏi phép đếm. SQL vẫn đếm ra 5, thẻ vẫn nói 5,
# nhưng hệ thống quyết định "không có gì" — và chỉ lộ ra khi đang quay.
OLDEST_DAYS=24
CUTOFF=$(grep -E '^enabled_from:' configs/policies/dw01/rework_support_v1.yaml          | sed 's/.*"\(.*\)".*/\1/')
if [[ -n "$CUTOFF" ]]; then
  CUTOFF_EPOCH=$(date -u -d "$CUTOFF" +%s 2>/dev/null || echo 0)
  OLDEST_EPOCH=$(date -u -d "$OLDEST_DAYS days ago" +%s)
  if [[ "$CUTOFF_EPOCH" -gt "$OLDEST_EPOCH" ]]; then
    echo "✖ Không gieo được: enabled_from = $CUTOFF nằm SAU bản ghi cũ nhất" >&2
    echo "  (${OLDEST_DAYS} ngày trước). Mọi bản ghi gieo sẽ bị loại khỏi phép" >&2
    echo "  đếm và thẻ hỗ trợ sẽ không hiện, dù SQL đếm ra đủ số." >&2
    echo "  Sửa: lùi enabled_from trong configs/policies/dw01/rework_support_v1.yaml" >&2
    exit 1
  fi
fi

$COMPOSE exec -T postgres psql -U "$PGU" -d dw -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;

\set tenant '''d6b43d0e-c3c6-5dbc-bc08-150621bd9a5d'''
\set ws     '''64764894-718d-5558-ba17-9a2949214063'''

-- Mọi bản ghi phải trỏ tới một hồ sơ có thật (FK). Dùng hồ sơ hoàn tất từ
-- seed_demo_cases.sh — nó không nằm trong mạch diễn nên không ảnh hưởng gì.
\set anchor '''c0000000-0000-4000-8000-000000000004'''

DELETE FROM tender.preparation_explanations;
DELETE FROM tender.preparation_rework_events
 WHERE id::text LIKE 'e0000000-0000-4000-8000-%';

-- Năm lần trả lại trong 30 ngày = chạm ngưỡng chặn; ba lần trong 7 ngày gần
-- nhất = chạm cả ngưỡng nhắc. Chặn cứng thắng khi cả hai cùng chạm.
--
-- Ba lần cùng nhóm "budget_mismatch" là CỐ Ý: đó là thứ làm thẻ hỗ trợ nói
-- được điều gì cụ thể thay vì chỉ đưa ra một con số. Một buổi demo mà thẻ chỉ
-- nói "bạn bị trả 5 lần" thì không khác gì bảng chấm công.
INSERT INTO tender.preparation_rework_events
  (id, tenant_id, workspace_id, case_id, creator_user_id, decided_by_user_id,
   checkpoint, reason_code, reason_text, policy_version, occurred_at)
SELECT
  v.id::uuid, :tenant, :ws, :anchor,
  (SELECT id FROM platform.users WHERE subject = 'dev|an.nguyen'),
  (SELECT id FROM platform.users WHERE subject = 'dev|chi.le'),
  v.checkpoint, v.reason_code, v.reason_text, '1.0.0',
  now() - (v.days_ago || ' days')::interval
FROM (VALUES
  ('e0000000-0000-4000-8000-000000000001', 2,  'intake', 'budget_mismatch',
   'Dự toán trên hồ sơ ghi 1,2 tỷ nhưng đề nghị mua sắm đã duyệt là 1,2 triệu.'),
  ('e0000000-0000-4000-8000-000000000002', 4,  'intake', 'budget_mismatch',
   'Đơn vị tiền tệ để trống, số tiền không đối chiếu được với PR.'),
  ('e0000000-0000-4000-8000-000000000003', 6,  'cp1',    'supplier_shortfall',
   'Hình thức chào giá cạnh tranh cần tối thiểu 3 nhà cung cấp, hồ sơ mới có 2.'),
  ('e0000000-0000-4000-8000-000000000004', 15, 'intake', 'budget_mismatch',
   'Dự toán chưa gồm thuế, lệch với PR đã duyệt.'),
  ('e0000000-0000-4000-8000-000000000005', 24, 'cp2',    'timeline_issue',
   'Hạn nộp hồ sơ ngắn hơn mức tối thiểu theo quy định hiện hành.')
) AS v(id, days_ago, checkpoint, reason_code, reason_text);

COMMIT;
SQL

echo "Lịch sử trả hồ sơ của An:"
$COMPOSE exec -T postgres psql -U "$PGU" -d dw -tAc \
  "select '  '||to_char(occurred_at,'DD/MM')||' | '||rpad(checkpoint,7)||' | '
        ||rpad(reason_code,20)||' | '||left(reason_text,50)
     from tender.preparation_rework_events order by occurred_at desc"
$COMPOSE exec -T postgres psql -U "$PGU" -d dw -tAc \
  "select '  → '||count(*) filter (where occurred_at > now() - interval '7 days')
        ||' lần trong 7 ngày (ngưỡng nhắc 3), '
        ||count(*) filter (where occurred_at > now() - interval '30 days')
        ||' lần trong 30 ngày (ngưỡng chặn 5)'
     from tender.preparation_rework_events"
echo "✔ An đang ở mức CHẶN CỨNG — câu mở hồ sơ mới tiếp theo sẽ bị từ chối."
