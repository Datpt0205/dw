#!/usr/bin/env bash
# =============================================================================
# DW01 demo reset — wipe chat context + old test cases for a clean demo.
#
# Deletes (demo data only):
#   - tender.chat_conversations        <- Ngọc's slot memory (the real context)
#   - tender.preparation_rework_events  <- returned-case tally (see note below)
#   - tender.preparation_explanations   <- written context submitted against it
#   - tender.preparation_* / documents <- old DW01 test cases + generated docs
#   - tender.approval_notification_jobs (queued/sent Slack cards)
#   - platform.channel_event_dedupe    (Slack event dedupe)
#   - platform.approval_requests/decisions with approval_type 'preparation.%'
#   - platform.worker_runs (+ checkpoints, tool_executions) of DW01 runs
#
# Keeps: users, memberships, roles, knowledge, audit_events (kiểm toán là
# append-only), meetings/tender vertical-slice data.
#
# Usage:  bash scripts/demo_reset.sh          (from repo root, stack running)
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

PGU=$(grep '^POSTGRES_USER=' .env | cut -d= -f2)
COMPOSE="docker compose --env-file .env -f infra/compose/docker-compose.yml"

echo "Trước khi xóa:"
$COMPOSE exec -T postgres psql -U "$PGU" -d dw -tAc \
  "select 'cases='||(select count(*) from tender.preparation_cases)
       ||' chats='||(select count(*) from tender.chat_conversations)
       ||' notif='||(select count(*) from tender.approval_notification_jobs)
       ||' rework='||(select count(*) from tender.preparation_rework_events)"

$COMPOSE exec -T postgres psql -U "$PGU" -d dw -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
-- Rework-support tally. MUST be cleared, and before the cases it points at.
--
-- Every retake that ends with a rejection leaves a row here, and the tally is
-- what decides whether somebody may open a new case. Three abandoned takes in
-- a week is exactly the threshold — leave these behind and the demo blocks An
-- on the opening line, on camera, for reasons nobody in the room can see.
--
-- Explanations survive a case delete on their own (ON DELETE SET NULL), and an
-- approved one lifts a block, so they go too.
DELETE FROM tender.preparation_explanations;
DELETE FROM tender.preparation_rework_events;
-- DW01 chat + case flow
DELETE FROM tender.approval_notification_jobs;
DELETE FROM tender.preparation_artifacts;
DELETE FROM tender.preparation_documents;
DELETE FROM tender.chat_conversations;
DELETE FROM tender.preparation_cases;
-- Slack channel event dedupe
DELETE FROM platform.channel_event_dedupe;
-- DW01 checkpoint approvals
DELETE FROM platform.approval_decisions WHERE request_id IN
  (SELECT id FROM platform.approval_requests WHERE approval_type LIKE 'preparation.%');
DELETE FROM platform.approval_requests WHERE approval_type LIKE 'preparation.%';
-- DW01 runs + durable graph state + tool audit rows
CREATE TEMP TABLE _dw01_runs AS
  SELECT id FROM platform.worker_runs
  WHERE worker_id = 'preparation' OR worker_id LIKE 'dw01%';
DELETE FROM platform.run_checkpoint_writes WHERE run_id IN (SELECT id FROM _dw01_runs);
DELETE FROM platform.run_checkpoints      WHERE run_id IN (SELECT id FROM _dw01_runs);
DELETE FROM platform.tool_executions      WHERE run_id IN (SELECT id FROM _dw01_runs);
DELETE FROM platform.worker_runs          WHERE id     IN (SELECT id FROM _dw01_runs);
COMMIT;
SQL

echo "Sau khi xóa:"
$COMPOSE exec -T postgres psql -U "$PGU" -d dw -tAc \
  "select 'cases='||(select count(*) from tender.preparation_cases)
       ||' chats='||(select count(*) from tender.chat_conversations)
       ||' notif='||(select count(*) from tender.approval_notification_jobs)
       ||' rework='||(select count(*) from tender.preparation_rework_events)"
echo "✔ DB sạch — Ngọc không còn nhớ gì từ các lần test cũ."
echo "  (Tin nhắn cũ trên Slack chỉ là hình ảnh, không phải trí nhớ của Ngọc."
echo "   Muốn khung chat trông sạch: uv run python scripts/slack_clear_dm.py)"
