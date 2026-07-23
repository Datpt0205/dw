"""Fixture: migrated runtime test database (fails loudly without infra)."""

from __future__ import annotations

import asyncio

import pytest
from runtime_harness import RuntimeUrls, recreate_database, run_migrations, runtime_urls


@pytest.fixture(scope="session")
def urls() -> RuntimeUrls:
    resolved = runtime_urls()
    try:
        asyncio.run(recreate_database(resolved.admin))
    except Exception as exc:
        pytest.fail(f"Postgres unreachable — run `make infra-up` first. Error: {exc}")
    result = run_migrations(resolved.migrator)
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}")
    return resolved
