"""Integration: real Qdrant + MinIO + Postgres — cross-tenant retrieval fails closed."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from minio import Minio
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# reuse the runtime harness (same infra, own database)
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
from dw_knowledge.adapters.hash_embedding import HashEmbeddingAdapter
from dw_knowledge.adapters.minio_storage import MinioObjectStorageAdapter
from dw_knowledge.adapters.qdrant_index import QdrantVectorIndexAdapter
from dw_knowledge.contracts import SearchQuery
from dw_knowledge.gateway import IngestDocumentCommand, KnowledgeGateway
from dw_platform.application.access_context import AccessContext

pytestmark = pytest.mark.integration

TENANT_A = uuid.UUID(int=0xAA00)
WORKSPACE_A = uuid.UUID(int=0xAA01)
TENANT_B = uuid.UUID(int=0xBB00)
WORKSPACE_B = uuid.UUID(int=0xBB01)


def make_context(tenant: uuid.UUID, workspace: uuid.UUID) -> AccessContext:
    return AccessContext(
        tenant_id=tenant,
        workspace_id=workspace,
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset({"knowledge.read"}),
        plan_id="professional",
    )


@pytest.fixture(scope="session")
def urls() -> RuntimeUrls:
    resolved = runtime_urls()
    import asyncio

    try:
        asyncio.run(recreate_database(resolved.admin))
    except Exception as exc:
        pytest.fail(f"Postgres unreachable — run `make infra-up`. Error: {exc}")
    result = run_migrations(resolved.migrator)
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade failed:\n{result.stderr}")
    return resolved


@pytest.fixture
async def gateway(urls: RuntimeUrls):
    engine = create_async_engine(urls.app, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    qdrant = AsyncQdrantClient(url=urls.qdrant_url)
    collection = f"dw_knowledge_test_{uuid.uuid4().hex[:8]}"
    minio_client = Minio(
        urls.minio_endpoint,
        access_key=urls.minio_access_key,
        secret_key=urls.minio_secret_key,
        secure=False,
    )
    gateway = KnowledgeGateway(
        session_factory=session_factory,
        vector_index=QdrantVectorIndexAdapter(client=qdrant, collection=collection),
        embeddings=HashEmbeddingAdapter(),
        object_storage=MinioObjectStorageAdapter(client=minio_client, bucket="dw-artifacts"),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )
    await gateway.ensure_ready()
    yield gateway
    await qdrant.delete_collection(collection)
    await qdrant.close()
    await engine.dispose()


SECRET_TEXT = (
    "Chính sách mua hàng nội bộ của Công ty Alpha: ngân sách tối đa cho một RFQ "
    "là 500 triệu đồng, cần hai chữ ký phê duyệt."
)


async def test_ingest_then_search_same_tenant_finds_evidence(gateway) -> None:
    context_a = make_context(TENANT_A, WORKSPACE_A)
    ingested = await gateway.ingest_document(
        IngestDocumentCommand(title="Chính sách mua hàng", content=SECRET_TEXT),
        context_a,
    )
    assert ingested.chunk_count >= 1

    results = await gateway.search(SearchQuery(text="chính sách mua hàng ngân sách RFQ"), context_a)
    assert results, "same tenant must find its own document"
    top = results[0]
    assert "500 triệu" in top.content
    assert top.evidence.source_document_id == ingested.document_id
    assert len(top.evidence.provenance_hash) == 64


async def test_cross_tenant_search_returns_nothing(gateway) -> None:
    context_a = make_context(TENANT_A, WORKSPACE_A)
    context_b = make_context(TENANT_B, WORKSPACE_B)
    await gateway.ingest_document(
        IngestDocumentCommand(title="Bí mật Alpha", content=SECRET_TEXT), context_a
    )

    # Tenant B runs the EXACT text of tenant A's secret — zero results.
    results = await gateway.search(SearchQuery(text=SECRET_TEXT), context_b)
    assert results == [], "cross-tenant retrieval must fail closed"


async def test_clearance_blocks_higher_classification(gateway) -> None:
    context = make_context(TENANT_A, WORKSPACE_A)  # clearance=internal
    await gateway.ingest_document(
        IngestDocumentCommand(
            title="Tài liệu mật",
            content="Lương thưởng ban điều hành năm 2026 chi tiết.",
            classification="restricted",
        ),
        context,
    )
    results = await gateway.search(SearchQuery(text="lương thưởng ban điều hành"), context)
    assert results == [], "internal clearance must not read restricted documents"
