"""Integration: memory write flow against real Postgres (RLS applied)."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "dw_agent_runtime" / "tests" / "integration"),
)
from runtime_harness import (
    RuntimeUrls,
    recreate_database,
    run_migrations,
    runtime_urls,
)

from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_knowledge.contracts import EvidenceRef
from dw_memory import tables
from dw_memory.contracts import MemoryType, WriteDecision
from dw_memory.policy import MemoryCandidate, MemoryWritePolicy
from dw_memory.service import MemoryService
from dw_platform.application.access_context import AccessContext

pytestmark = pytest.mark.integration

TENANT = uuid.UUID(int=0xCC00)
WORKSPACE = uuid.UUID(int=0xCC01)


@pytest.fixture(scope="session")
def urls() -> RuntimeUrls:
    resolved = runtime_urls()
    try:
        asyncio.run(recreate_database(resolved.admin))
    except Exception as exc:
        pytest.fail(f"Postgres unreachable — run `make infra-up`. Error: {exc}")
    result = run_migrations(resolved.migrator)
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade failed:\n{result.stderr}")
    return resolved


@pytest.fixture
async def service(urls: RuntimeUrls):
    engine = create_async_engine(urls.app, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield (
        MemoryService(
            session_factory=session_factory,
            policy=MemoryWritePolicy(),
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
        ),
        session_factory,
    )
    await engine.dispose()


def make_context() -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset({"work_ops.write"}),
        plan_id="professional",
    )


def make_evidence() -> EvidenceRef:
    return EvidenceRef(
        evidence_id=uuid.uuid4(),
        source_document_id=uuid.uuid4(),
        source_version="1",
        relevance_score=0.95,
        classification="internal",
        provenance_hash=hashlib.sha256(b"meeting-transcript").hexdigest(),
    )


async def _count(session_factory, table) -> int:
    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT)}
        )
        result = await session.execute(sa.select(sa.func.count()).select_from(table))
        return int(result.scalar_one())


async def test_auto_write_persists_item_with_provenance(service) -> None:
    memory_service, session_factory = service
    result = await memory_service.propose(
        MemoryCandidate(
            worker_id="work_ops",
            memory_type=MemoryType.COMMITMENT,
            content="Anh An cam kết gửi hợp đồng trước thứ Sáu.",
            provenance_refs=(make_evidence(),),
            confidence=0.92,
        ),
        make_context(),
        created_by_run_id=uuid.uuid4(),
    )
    assert result.outcome.decision is WriteDecision.AUTO_WRITE
    assert result.item is not None
    assert await _count(session_factory, tables.items) >= 1
    assert await _count(session_factory, tables.write_candidates) >= 1


async def test_low_confidence_goes_to_review_without_item(service) -> None:
    memory_service, session_factory = service
    items_before = await _count(session_factory, tables.items)
    result = await memory_service.propose(
        MemoryCandidate(
            worker_id="work_ops",
            memory_type=MemoryType.PREFERENCE,
            content="Có thể chị Bình thích nhận báo cáo qua Slack.",
            provenance_refs=(make_evidence(),),
            confidence=0.6,
        ),
        make_context(),
        created_by_run_id=uuid.uuid4(),
    )
    assert result.outcome.decision is WriteDecision.REVIEW
    assert result.item is None
    assert await _count(session_factory, tables.items) == items_before


async def test_no_provenance_rejected(service) -> None:
    memory_service, _ = service
    result = await memory_service.propose(
        MemoryCandidate(
            worker_id="work_ops",
            memory_type=MemoryType.SEMANTIC,
            content="Thông tin không có nguồn.",
            provenance_refs=(),
            confidence=0.99,
        ),
        make_context(),
        created_by_run_id=uuid.uuid4(),
    )
    assert result.outcome.decision is WriteDecision.REJECT
    assert result.item is None
