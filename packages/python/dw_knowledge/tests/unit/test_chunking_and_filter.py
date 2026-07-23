import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_knowledge.chunking import chunk_text
from dw_knowledge.contracts import SearchQuery
from dw_knowledge.gateway import KnowledgeGateway, build_trusted_filter
from dw_knowledge.ports import TrustedSearchFilter, VectorHit
from dw_platform.application.access_context import AccessContext

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def make_context(**overrides: object) -> AccessContext:
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "principal_id": uuid.uuid4(),
        "roles": frozenset({"member"}),
        "scopes": frozenset({"knowledge.read"}),
        "plan_id": "professional",
    }
    defaults.update(overrides)
    return AccessContext(**defaults)


# --- chunking ---------------------------------------------------------------


def test_chunking_is_deterministic_and_offset_preserving() -> None:
    text = "\n\n".join(f"Đoạn văn số {i}. " + "nội dung " * 40 for i in range(6))
    first = chunk_text(text)
    second = chunk_text(text)
    assert first == second
    assert len(first) > 1
    for chunk in first:
        assert text[chunk.start_offset : chunk.end_offset].strip() == chunk.content
        assert len(chunk.provenance_hash) == 64


def test_chunking_rejects_bad_params() -> None:
    with pytest.raises(ValueError):
        chunk_text("x", max_chars=0)
    with pytest.raises(ValueError):
        chunk_text("x", max_chars=100, overlap_chars=100)


def test_chunking_empty_text() -> None:
    assert chunk_text("   \n  ") == []


# --- trusted filter ----------------------------------------------------------


def test_trusted_filter_comes_only_from_context() -> None:
    context = make_context(clearance="internal")
    trusted = build_trusted_filter(context, "tender")
    assert trusted.tenant_id == context.tenant_id
    assert trusted.workspace_id == context.workspace_id
    assert trusted.allowed_classifications == ("internal",)
    assert f"user:{context.principal_id}" in trusted.acl_principals
    assert "role:member" in trusted.acl_principals


def test_clearance_mapping_fails_closed_for_unknown_values() -> None:
    trusted = build_trusted_filter(make_context(clearance="galactic"), "shared")
    assert trusted.allowed_classifications == ("internal",)


def test_confidential_clearance_widens_but_never_restricted() -> None:
    trusted = build_trusted_filter(make_context(clearance="confidential"), "shared")
    assert "restricted" not in trusted.allowed_classifications


# --- gateway search always injects the filter --------------------------------


@dataclass
class CapturingIndex:
    captured: list[TrustedSearchFilter] = field(default_factory=list)
    hits: list[VectorHit] = field(default_factory=list)

    async def ensure_ready(self, vector_dimension: int) -> None: ...

    async def upsert(self, chunks) -> None: ...

    async def search(self, vector, trusted_filter, top_k):
        self.captured.append(trusted_filter)
        return self.hits


@dataclass
class FakeEmbedding:
    @property
    def dimension(self) -> int:
        return 4

    async def embed(self, texts):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


@dataclass
class FakeStorage:
    async def put_object(self, key: str, data: bytes, content_type: str) -> str:
        return f"s3://fake/{key}"

    async def get_object(self, key: str) -> bytes:
        return b""


def make_gateway(index: CapturingIndex) -> KnowledgeGateway:
    return KnowledgeGateway(
        session_factory=cast("async_sessionmaker[AsyncSession]", None),  # search never touches SQL
        vector_index=index,
        embeddings=FakeEmbedding(),
        object_storage=FakeStorage(),
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
    )


async def test_search_always_carries_tenant_filter_from_context() -> None:
    index = CapturingIndex()
    gateway = make_gateway(index)
    context = make_context()

    await gateway.search(SearchQuery(text="chính sách mua hàng"), context)

    assert len(index.captured) == 1
    trusted = index.captured[0]
    assert trusted.tenant_id == context.tenant_id
    assert trusted.workspace_id == context.workspace_id
    # There is no code path for the caller to override these: SearchQuery has
    # no such fields (extra="forbid") and the gateway rebuilds the filter from
    # AccessContext on every call.


async def test_search_applies_min_relevance_and_document_filter() -> None:
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()

    def hit(document_id: uuid.UUID, score: float) -> VectorHit:
        return VectorHit(
            chunk_id=uuid.uuid4(),
            document_id=document_id,
            score=score,
            content="nội dung",
            classification="internal",
            source_version="1",
            provenance_hash="a" * 64,
        )

    index = CapturingIndex(hits=[hit(doc_a, 0.9), hit(doc_b, 0.9), hit(doc_a, 0.1)])
    gateway = make_gateway(index)

    results = await gateway.search(
        SearchQuery(text="q", min_relevance=0.5, document_ids=(doc_a,)),
        make_context(),
    )
    assert len(results) == 1
    assert results[0].evidence.source_document_id == doc_a
    assert results[0].evidence.relevance_score == 0.9
