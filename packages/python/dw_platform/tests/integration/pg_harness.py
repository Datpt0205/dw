"""Shared Postgres harness for integration tests.

Requires `make infra-up` (Docker postgres on localhost:5432). Fails loudly when
the database is unreachable — integration tests never silently skip.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]


def _load_dotenv_defaults() -> dict[str, str]:
    """Minimal .env reader so tests share compose credentials; env wins."""
    values: dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if k in values or k.startswith("DW_")})
    return values


# Lab sandbox: tên DB test đọc qua chính loader .env ở trên, nên `make` lẫn
# `uv run pytest` trần đều thấy — quan trọng vì _recreate_database chạy
# DROP DATABASE ... WITH (FORCE) đúng trên cái tên này.
TEST_DB = _load_dotenv_defaults().get("DW_TEST_DB_NAME", "dw_test")


@dataclass(frozen=True)
class DatabaseUrls:
    admin: str  # superuser on postgres db (create/drop test db)
    migrator: str  # dw_migrator on dw_test (BYPASSRLS maintenance)
    app: str  # dw_app on dw_test (RLS enforced)


def _database_urls() -> DatabaseUrls:
    env = _load_dotenv_defaults()
    host = env.get("DW_TEST_DB_HOST", "localhost")
    port = env.get("DW_TEST_DB_PORT", "5432")
    admin_user = env.get("POSTGRES_USER", "dw_admin")
    admin_password = env.get("POSTGRES_PASSWORD", "change-me-admin")
    migrator_password = env.get("DW_DB_MIGRATOR_PASSWORD", "change-me-migrator")
    app_password = env.get("DW_DB_APP_PASSWORD", "change-me-app")
    return DatabaseUrls(
        admin=f"postgresql+asyncpg://{admin_user}:{admin_password}@{host}:{port}/postgres",
        migrator=f"postgresql+asyncpg://dw_migrator:{migrator_password}@{host}:{port}/{TEST_DB}",
        app=f"postgresql+asyncpg://dw_app:{app_password}@{host}:{port}/{TEST_DB}",
    )


async def _recreate_database(admin_url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            await conn.execute(text(f"CREATE DATABASE {TEST_DB} OWNER dw_migrator"))
    finally:
        await engine.dispose()


def run_alembic(command: list[str], database_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(REPO_ROOT / "db" / "alembic.ini"), *command],
        env={**os.environ, "DW_DATABASE_URL": database_url},
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
