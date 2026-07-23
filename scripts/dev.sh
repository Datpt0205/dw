#!/usr/bin/env bash
# Run API + worker + web concurrently for local development.
# Prerequisite: `make infra-up` (or point env vars at your own services).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

pids=()
cleanup() {
  echo ""
  echo ">> shutting down dev processes"
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo ">> starting API on :${DW_API_PORT:-8000}"
uv run uvicorn dw_api.main:app --reload --port "${DW_API_PORT:-8000}" &
pids+=($!)

echo ">> starting worker"
DW_WORKER_HEARTBEAT_FILE="${DW_WORKER_HEARTBEAT_FILE:-.dw/worker-heartbeat}" \
  uv run python -m dw_worker.main &
pids+=($!)

echo ">> starting web on :3000"
pnpm --filter @dw/web dev &
pids+=($!)

wait
