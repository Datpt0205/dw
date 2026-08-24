"""Postgres/Qdrant/MinIO harness for runtime integration tests.

Uses its own database (dw_test_runtime) so it never fights with the platform
test database. Requires `make infra-up`; fails loudly when infra is missing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    values.update(
        {
            k: v
            for k, v in os.environ.items()
            if k.startswith(("DW_", "POSTGRES", "MINIO", "QDRANT"))
        }
    )
    return values


# Lab sandbox: tên DB test đọc qua chính load_env() ở trên, nên `make` lẫn
# `uv run pytest` trần đều thấy — quan trọng vì _recreate_database chạy
# DROP DATABASE ... WITH (FORCE) đúng trên cái tên này.
TEST_DB = load_env().get("DW_TEST_RUNTIME_DB_NAME", "dw_test_runtime")


@dataclass(frozen=True)
class RuntimeUrls:
    admin: str
    migrator: str
    app: str
    qdrant_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str


def runtime_urls() -> RuntimeUrls:
    env = load_env()
    host = env.get("DW_TEST_DB_HOST", "localhost")
    port = env.get("DW_TEST_DB_PORT", "5432")
    admin_user = env.get("POSTGRES_USER", "dw_admin")
    admin_password = env.get("POSTGRES_PASSWORD", "change-me-admin")
    migrator_password = env.get("DW_DB_MIGRATOR_PASSWORD", "change-me-migrator")
    app_password = env.get("DW_DB_APP_PASSWORD", "change-me-app")
    return RuntimeUrls(
        admin=f"postgresql+asyncpg://{admin_user}:{admin_password}@{host}:{port}/postgres",
        migrator=f"postgresql+asyncpg://dw_migrator:{migrator_password}@{host}:{port}/{TEST_DB}",
        app=f"postgresql+asyncpg://dw_app:{app_password}@{host}:{port}/{TEST_DB}",
        qdrant_url=env.get("QDRANT_URL", "http://localhost:6333"),
        minio_endpoint="localhost:9000",
        minio_access_key=env.get("MINIO_ROOT_USER", "dw-minio"),
        minio_secret_key=env.get("MINIO_ROOT_PASSWORD", "change-me-minio"),
    )


async def recreate_database(admin_url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            await conn.execute(text(f"CREATE DATABASE {TEST_DB} OWNER dw_migrator"))
    finally:
        await engine.dispose()


def run_migrations(database_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(REPO_ROOT / "db" / "alembic.ini"),
            "upgrade",
            "head",
        ],
        env={**os.environ, "DW_DATABASE_URL": database_url},
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


# --- shared test context builders -------------------------------------------

import uuid  # noqa: E402

from dw_agent_runtime.contracts import RunContext  # noqa: E402

TENANT_A = uuid.UUID(int=0xA00)
WORKSPACE_A = uuid.UUID(int=0xA01)
TENANT_B = uuid.UUID(int=0xB00)
WORKSPACE_B = uuid.UUID(int=0xB01)


def make_run_context(
    *,
    tenant: uuid.UUID = TENANT_A,
    workspace: uuid.UUID = WORKSPACE_A,
    run_id: uuid.UUID | None = None,
    scopes: frozenset[str] = frozenset({"work_ops.write", "work_ops.read"}),
) -> RunContext:
    return RunContext(
        run_id=run_id or uuid.uuid4(),
        tenant_id=tenant,
        workspace_id=workspace,
        actor_id=uuid.uuid4(),
        worker_id="demo_approval",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=scopes,
        trace_id=f"trace-{uuid.uuid4().hex[:8]}",
    )
