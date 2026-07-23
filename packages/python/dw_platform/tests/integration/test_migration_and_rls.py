"""Integration: blank-DB migration, RLS isolation, default-deny, append-only audit."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls, run_alembic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.adapters.persistence import tables

pytestmark = pytest.mark.integration

TENANT_A = uuid.UUID(int=0xA)
TENANT_B = uuid.UUID(int=0xB)
WORKSPACE_A = uuid.UUID(int=0xA1)
WORKSPACE_B = uuid.UUID(int=0xB1)
NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _set_tenant(conn: AsyncConnection, tenant_id: uuid.UUID) -> None:
    await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})


async def _seed_tenant_fixture(
    engine: AsyncEngine, tenant_id: uuid.UUID, workspace_id: uuid.UUID, slug: str
) -> None:
    """Create tenant + workspace + one approval request as dw_app under RLS."""
    async with engine.connect() as conn:
        async with conn.begin():
            await _set_tenant(conn, tenant_id)
            await conn.execute(
                sa.insert(tables.tenants).values(id=tenant_id, slug=slug, name=slug),
            )
            await conn.execute(
                sa.insert(tables.workspaces).values(
                    id=workspace_id, tenant_id=tenant_id, slug="main", name="Main"
                )
            )
            await conn.execute(
                sa.insert(tables.approval_requests).values(
                    id=uuid.uuid5(tenant_id, "approval-1"),
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    approval_type="test.approval",
                    requested_by=uuid.uuid4(),
                    reason="fixture",
                )
            )


def test_migration_downgrade_upgrade_roundtrip(db_urls: DatabaseUrls) -> None:
    """Blank DB was migrated by the fixture; downgrade to base and re-upgrade."""
    result = run_alembic(["downgrade", "base"], db_urls.migrator)
    assert result.returncode == 0, result.stderr
    result = run_alembic(["upgrade", "head"], db_urls.migrator)
    assert result.returncode == 0, result.stderr


async def test_rls_tenant_isolation(app_engine: AsyncEngine) -> None:
    await _seed_tenant_fixture(app_engine, TENANT_A, WORKSPACE_A, "iso-tenant-a")
    await _seed_tenant_fixture(app_engine, TENANT_B, WORKSPACE_B, "iso-tenant-b")

    async with app_engine.connect() as conn:
        async with conn.begin():
            await _set_tenant(conn, TENANT_A)
            rows = (await conn.execute(sa.select(tables.approval_requests.c.tenant_id))).all()
            assert rows, "tenant A must see its own rows"
            assert {row.tenant_id for row in rows} == {TENANT_A}

        async with conn.begin():
            await _set_tenant(conn, TENANT_B)
            rows = (await conn.execute(sa.select(tables.approval_requests.c.tenant_id))).all()
            assert {row.tenant_id for row in rows} == {TENANT_B}, "tenant B must never see A"


async def test_rls_default_deny_without_context(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        async with conn.begin():
            rows = (await conn.execute(sa.select(tables.approval_requests))).all()
            assert rows == [], "no tenant context must mean zero rows (fail closed)"
            tenants = (await conn.execute(sa.select(tables.tenants))).all()
            assert tenants == []


async def test_rls_blocks_cross_tenant_write(app_engine: AsyncEngine) -> None:
    """Context = tenant B, but row claims tenant A → WITH CHECK must reject."""
    async with app_engine.connect() as conn:
        async with conn.begin():
            await _set_tenant(conn, TENANT_B)
            with pytest.raises(sa.exc.DBAPIError) as excinfo:
                await conn.execute(
                    sa.insert(tables.approval_requests).values(
                        id=uuid.uuid4(),
                        tenant_id=TENANT_A,  # spoof attempt
                        workspace_id=WORKSPACE_A,
                        approval_type="attack.cross_tenant",
                        requested_by=uuid.uuid4(),
                        reason="should fail",
                    )
                )
            assert "row-level security" in str(excinfo.value).lower()


async def test_audit_is_append_only_for_app_role(app_engine: AsyncEngine) -> None:
    event_id = uuid.uuid4()
    async with app_engine.connect() as conn:
        async with conn.begin():
            await _set_tenant(conn, TENANT_A)
            await conn.execute(
                sa.insert(tables.audit_events).values(
                    id=event_id,
                    tenant_id=TENANT_A,
                    workspace_id=WORKSPACE_A,
                    actor_id=uuid.uuid4(),
                    action="test.audit",
                    resource_type="test",
                    resource_id="r-1",
                    occurred_at=NOW,
                )
            )

    async with app_engine.connect() as conn:
        async with conn.begin():
            await _set_tenant(conn, TENANT_A)
            with pytest.raises(sa.exc.DBAPIError) as update_err:
                await conn.execute(
                    sa.update(tables.audit_events)
                    .where(tables.audit_events.c.id == event_id)
                    .values(action="tampered")
                )
            assert "permission denied" in str(update_err.value).lower()

    async with app_engine.connect() as conn:
        async with conn.begin():
            await _set_tenant(conn, TENANT_A)
            with pytest.raises(sa.exc.DBAPIError) as delete_err:
                await conn.execute(
                    sa.delete(tables.audit_events).where(tables.audit_events.c.id == event_id)
                )
            assert "permission denied" in str(delete_err.value).lower()
