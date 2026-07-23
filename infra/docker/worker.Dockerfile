# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Stage 1 — builder
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:0.11.31-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY packages/python/dw_kernel/pyproject.toml packages/python/dw_kernel/pyproject.toml
COPY packages/python/dw_platform/pyproject.toml packages/python/dw_platform/pyproject.toml
COPY packages/python/dw_agent_runtime/pyproject.toml packages/python/dw_agent_runtime/pyproject.toml
COPY packages/python/dw_knowledge/pyproject.toml packages/python/dw_knowledge/pyproject.toml
COPY packages/python/dw_memory/pyproject.toml packages/python/dw_memory/pyproject.toml
COPY packages/python/dw_connectors/pyproject.toml packages/python/dw_connectors/pyproject.toml
COPY packages/python/dw_tender/pyproject.toml packages/python/dw_tender/pyproject.toml
COPY packages/python/dw_work_ops/pyproject.toml packages/python/dw_work_ops/pyproject.toml
COPY packages/python/dw_observability/pyproject.toml packages/python/dw_observability/pyproject.toml
COPY packages/python/dw_evals/pyproject.toml packages/python/dw_evals/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --no-dev --package dw-worker

COPY packages/python packages/python
COPY apps/worker apps/worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package dw-worker

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

RUN groupadd --gid 1001 dw && useradd --uid 1001 --gid dw --create-home dw

WORKDIR /app
COPY --from=builder --chown=dw:dw /build/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DW_WORKER_HEARTBEAT_FILE=/home/dw/heartbeat

USER dw

HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 \
    CMD ["python", "-m", "dw_worker.health"]

CMD ["python", "-m", "dw_worker.main"]
