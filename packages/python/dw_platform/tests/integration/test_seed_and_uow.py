"""Integration: idempotent seed, membership lookup, UoW with tenant context."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from pg_harness import REPO_ROOT, DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.domain.approval import ApprovalRequest, DecisionOutcome
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.outbox import OutboxEvent

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)

SEED_TABLES = ("tenants", "workspaces", "users", "roles", "plans", "memberships", "entitlements")


def run_seed(database_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "seed_demo.py")],
        env={**os.environ, "DW_DATABASE_URL": database_url},
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
async def migrator_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _table_counts(engine: AsyncEngine) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with engine.connect() as conn:
        for name in SEED_TABLES:
            table = getattr(tables, name)
            counts[name] = (
                await conn.execute(sa.select(sa.func.count()).select_from(table))
            ).scalar_one()
    return counts


async def test_seed_runs_twice_without_duplicates(
    db_urls: DatabaseUrls, migrator_engine: AsyncEngine
) -> None:
    first = run_seed(db_urls.migrator)
    assert first.returncode == 0, first.stderr
    counts_after_first = await _table_counts(migrator_engine)
    assert counts_after_first["tenants"] >= 2
    assert counts_after_first["memberships"] >= 5

    second = run_seed(db_urls.migrator)
    assert second.returncode == 0, second.stderr
    counts_after_second = await _table_counts(migrator_engine)
    assert counts_after_second == counts_after_first, "seed must be idempotent"


async def test_membership_lookup_confirms_and_denies(
    db_urls: DatabaseUrls, migrator_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    run_seed(db_urls.migrator)
    async with migrator_engine.connect() as conn:
        alpha_id = (
            await conn.execute(
                sa.select(tables.tenants.c.id).where(tables.tenants.c.slug == "tenant-alpha")
            )
        ).scalar_one()
        alpha_ws = (
            await conn.execute(
                sa.select(tables.workspaces.c.id).where(tables.workspaces.c.tenant_id == alpha_id)
            )
        ).scalar_one()
        beta_id = (
            await conn.execute(
                sa.select(tables.tenants.c.id).where(tables.tenants.c.slug == "tenant-beta")
            )
        ).scalar_one()
        beta_ws = (
            await conn.execute(
                sa.select(tables.workspaces.c.id).where(tables.workspaces.c.tenant_id == beta_id)
            )
        ).scalar_one()

    lookup = SqlMembershipLookup(
        async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    )

    access = await lookup.find_access("dev|an.nguyen", "dw-dev", alpha_id, alpha_ws)
    assert access is not None
    assert access.plan_id == "professional"
    assert "work_ops.write" in access.scopes
    assert "work_ops_worker" in access.feature_flags

    # Same verified subject, foreign tenant → fail closed.
    assert await lookup.find_access("dev|an.nguyen", "dw-dev", beta_id, beta_ws) is None
    assert await lookup.find_access("dev|nobody", "dw-dev", alpha_id, alpha_ws) is None


async def test_uow_persists_approval_audit_outbox_under_rls(
    db_urls: DatabaseUrls, migrator_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    run_seed(db_urls.migrator)
    async with migrator_engine.connect() as conn:
        alpha_id = (
            await conn.execute(
                sa.select(tables.tenants.c.id).where(tables.tenants.c.slug == "tenant-alpha")
            )
        ).scalar_one()
        alpha_ws = (
            await conn.execute(
                sa.select(tables.workspaces.c.id).where(tables.workspaces.c.tenant_id == alpha_id)
            )
        ).scalar_one()

    context = AccessContext(
        tenant_id=alpha_id,
        workspace_id=alpha_ws,
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset({"work_ops.write"}),
        plan_id="professional",
    )
    factory = SqlPlatformUnitOfWorkFactory(
        async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    )

    request = ApprovalRequest(
        id=uuid.uuid4(),
        tenant_id=TenantId(alpha_id),
        workspace_id=WorkspaceId(alpha_ws),
        approval_type="work_ops.dispatch_actions",
        requested_by=UserId(context.principal_id),
        reason="integration test",
    )
    async with factory(context) as uow:
        await uow.approvals.add(request)
        await uow.audit.append(
            AuditEvent(
                id=uuid.uuid4(),
                tenant_id=TenantId(alpha_id),
                workspace_id=WorkspaceId(alpha_ws),
                actor_id=UserId(context.principal_id),
                action="approval.requested",
                resource_type="approval_request",
                resource_id=str(request.id),
                occurred_at=NOW,
            )
        )
        await uow.outbox.add(
            OutboxEvent(
                id=uuid.uuid4(),
                tenant_id=TenantId(alpha_id),
                workspace_id=WorkspaceId(alpha_ws),
                event_type="platform.approval.requested",
                schema_version="1.0",
                aggregate_id=request.id,
                occurred_at=NOW,
            )
        )
        await uow.commit()

    # Read back + decide in a second transaction.
    async with factory(context) as uow:
        loaded = await uow.approvals.get(request.id)
        assert loaded is not None and loaded.status.value == "pending"
        decision = loaded.decide(
            decision_id=uuid.uuid4(),
            decided_by=UserId(context.principal_id),
            outcome=DecisionOutcome.APPROVED,
            decided_at=NOW,
        )
        await uow.approvals.save(loaded)
        await uow.approvals.add_decision(decision)
        await uow.commit()

    async with factory(context) as uow:
        final = await uow.approvals.get(request.id)
        assert final is not None and final.status.value == "approved"
        pending_outbox = await uow.outbox.list_unprocessed()
        assert any(e.aggregate_id == request.id for e in pending_outbox)
