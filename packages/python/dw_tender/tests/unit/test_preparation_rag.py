"""RAG grounding in the DW01 draft_* nodes (B6): the _cite helper.

Verifies retrieval is injected into artifact drafting via the knowledge gateway,
that the gateway is called with the caller's context (never a caller-supplied
filter), and that drafting degrades gracefully with no gateway / on failure.
"""

from __future__ import annotations

import uuid

import pytest

from dw_knowledge.contracts import EvidenceChunk, EvidenceRef
from dw_tender.workflows.preparation_v1.nodes import PreparationNodes
from dw_tender.workflows.preparation_v1.services import PreparationServices

try:
    from dw_agent_runtime.contracts import RunContext
except Exception:  # pragma: no cover
    RunContext = None  # type: ignore[assignment]

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
ACTOR = uuid.uuid4()


def _run_context():
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        actor_id=ACTOR,
        worker_id="dw01",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=frozenset({"knowledge.read"}),
        trace_id="trace-1",
    )


def _chunk(text: str, score: float) -> EvidenceChunk:
    return EvidenceChunk(
        content=text,
        evidence=EvidenceRef(
            evidence_id=uuid.uuid4(),
            source_document_id=uuid.uuid4(),
            source_version="1",
            quote=text[:80],
            relevance_score=score,
            classification="internal",
            provenance_hash="a" * 64,
        ),
    )


class FakeGateway:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    async def search(self, query, context):
        self.calls.append((query.text, query.domain, context.tenant_id))
        return self.chunks


def _services(knowledge) -> PreparationServices:
    # _cite touches only `.knowledge`; the rest are unused stubs here.
    return PreparationServices(
        uow_factory=None,  # type: ignore[arg-type]
        storage=None,  # type: ignore[arg-type]
        rules=None,  # type: ignore[arg-type]
        suppliers=(),
        clock=None,  # type: ignore[arg-type]
        id_generator=None,  # type: ignore[arg-type]
        knowledge=knowledge,
    )


@pytest.mark.asyncio
async def test_cite_returns_citations_from_gateway() -> None:
    gw = FakeGateway([_chunk("Điều 22. Đấu thầu rộng rãi...", 0.91), _chunk("Điều 43...", 0.7)])
    nodes = PreparationNodes(_services(gw))
    citations = await nodes._cite(_run_context(), "hình thức lựa chọn nhà thầu", domain="legal")

    assert len(citations) == 2
    assert citations[0]["relevance_score"] == pytest.approx(0.91)
    assert "source_document_id" in citations[0] and "quote" in citations[0]
    # Gateway called with our domain + a context scoped to our tenant.
    assert gw.calls == [("hình thức lựa chọn nhà thầu", "legal", TENANT)]


@pytest.mark.asyncio
async def test_cite_no_gateway_degrades_to_empty() -> None:
    nodes = PreparationNodes(_services(None))
    assert await nodes._cite(_run_context(), "bất kỳ", domain="legal") == []


@pytest.mark.asyncio
async def test_cite_swallows_retrieval_failure() -> None:
    class Boom:
        async def search(self, query, context):
            raise RuntimeError("qdrant down")

    nodes = PreparationNodes(_services(Boom()))
    # Retrieval is best-effort grounding — a failure must not break drafting.
    assert await nodes._cite(_run_context(), "x", domain="legal") == []
