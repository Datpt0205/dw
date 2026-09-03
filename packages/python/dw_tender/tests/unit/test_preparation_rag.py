"""RAG grounding in the DW01 draft_* nodes (B6): the _cite helper.

Verifies retrieval is injected into artifact drafting via the knowledge gateway,
that the gateway is called with the caller's context (never a caller-supplied
filter), and that drafting degrades gracefully with no gateway / on failure.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from dw_agent_runtime.contracts import RunContext
from dw_knowledge.contracts import EvidenceChunk, EvidenceRef
from dw_tender.application.preparation.drafts import (
    CriteriaDraft,
    SolicitationDraft,
    WeightedCriterion,
)
from dw_tender.application.preparation.legal import (
    LEGAL_WINDOW_QUERY,
    LegalConstraintExtraction,
)
from dw_tender.workflows.preparation_v1.nodes import PreparationNodes, _grounding_source
from dw_tender.workflows.preparation_v1.services import PreparationServices

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
ACTOR = uuid.uuid4()


def _run_context() -> RunContext:
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


def _chunk(text: str, score: float, uri: str | None = None) -> EvidenceChunk:
    """``uri`` is what separates a live lookup from a read off the shelf."""
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
            source_uri=uri,
        ),
    )


class FakeGateway:
    def __init__(self, chunks: list[EvidenceChunk]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[str, str, uuid.UUID]] = []

    async def search(self, query: Any, context: Any) -> list[EvidenceChunk]:
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
        async def search(self, query: Any, context: Any) -> list[EvidenceChunk]:
            raise RuntimeError("qdrant down")

    nodes = PreparationNodes(_services(Boom()))
    # Retrieval is best-effort grounding — a failure must not break drafting.
    assert await nodes._cite(_run_context(), "x", domain="legal") == []


def test_a_citation_with_no_link_behind_it_is_marked_as_coming_from_the_shelf() -> None:
    """The approver's one blind spot, made visible.

    A live lookup and a read from the ingested corpus produce citations that
    look identical on an approval card — same quote, same relevance, same
    confident tone. Only one of them was true this morning. The difference is
    already in the evidence (``source_uri`` is what a reader could click), so
    the drafting node reads it rather than asking how retrieval was configured
    — which is the point, since the case worth catching is the one where it WAS
    configured for live search and silently reached nobody.
    """
    live = [{"quote": "…18 ngày…", "source_uri": "https://luatvietnam.vn/dieu-45"}]
    indexed = [{"quote": "…18 ngày…", "source_document_id": str(uuid.uuid4())}]

    assert _grounding_source(live) == "live"
    assert _grounding_source(indexed) == "indexed"
    assert _grounding_source([]) == "not_available"


def test_one_live_source_among_several_still_counts_as_live() -> None:
    """Mixed results mean the sources were reachable, which is what this reports."""
    assert (
        _grounding_source(
            [
                {"quote": "a", "source_document_id": str(uuid.uuid4())},
                {"quote": "b", "source_uri": "https://vanban.chinhphu.vn/x"},
            ]
        )
        == "live"
    )


# --- asking the law again, at signature time ---------------------------------


PASSAGE_18 = (
    "Điều 45. Thời gian tổ chức lựa chọn nhà thầu. 1. Thời gian chuẩn bị hồ sơ "
    "dự thầu đối với đấu thầu rộng rãi trong nước tối thiểu là 18 ngày, kể từ "
    "ngày đầu tiên hồ sơ mời thầu được phát hành đến ngày có thời điểm đóng thầu."
)


class FakeModelGateway:
    """Returns a prepared extraction, or raises, or is simply absent."""

    def __init__(self, extraction: Any = None, raises: Exception | None = None) -> None:
        self._extraction = extraction
        self._raises = raises
        self.calls = 0

    async def generate_structured(self, request: Any, output_type: Any, *, run_context: Any) -> Any:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._extraction


def _nodes(knowledge: Any, model: Any = None) -> PreparationNodes:
    services = PreparationServices(
        uow_factory=None,  # type: ignore[arg-type]
        storage=None,  # type: ignore[arg-type]
        rules=None,  # type: ignore[arg-type]
        suppliers=(),
        clock=None,  # type: ignore[arg-type]
        id_generator=None,  # type: ignore[arg-type]
        knowledge=knowledge,
        model_gateway=model,
    )
    return PreparationNodes(services)


@pytest.mark.asyncio
async def test_the_gate_asks_the_law_the_same_question_the_draft_asked() -> None:
    """Comparing two answers means nothing if the question changed between them.

    Both sides go through ``LEGAL_WINDOW_QUERY`` — which also makes the second
    ask a cache hit rather than a second paid search.
    """
    gateway = FakeGateway([_chunk(PASSAGE_18, 0.9, "https://luatvietnam.vn/dieu-45")])
    model = FakeModelGateway(
        LegalConstraintExtraction(
            min_bid_preparation_days=18,
            article_ref="Điều 45 khoản 1",
            source_quote="Thời gian chuẩn bị hồ sơ dự thầu đối với đấu thầu rộng rãi trong "
            "nước tối thiểu là 18 ngày",
        )
    )

    days, source = await _nodes(gateway, model)._live_legal_minimum(
        _run_context(), "đấu thầu rộng rãi"
    )

    assert days == 18
    assert source == "live", "đoạn có source_uri thì phải được ghi là tra trực tuyến"
    assert gateway.calls[0][0] == LEGAL_WINDOW_QUERY
    assert gateway.calls[0][1] == "legal"


@pytest.mark.asyncio
async def test_a_search_outage_reads_as_no_answer_never_as_a_new_deadline() -> None:
    """The failure that would turn an incident into a blocked procurement.

    ``_cite`` swallows retrieval errors and returns ``[]`` by design, so the
    only correct thing to do with an empty result is say "no figure" and let the
    drafted one stand. Returning anything else here — or raising — would mean a
    provider outage stops packages being signed.
    """

    class DeadGateway:
        async def search(self, query: Any, context: Any) -> list[EvidenceChunk]:
            raise RuntimeError("cả chuỗi provider chết")

    model = FakeModelGateway()

    days, source = await _nodes(DeadGateway(), model)._live_legal_minimum(_run_context(), "x")

    assert (days, source) == (None, "not_available")
    assert model.calls == 0, "không có đoạn nào thì đừng tốn một lượt gọi model"


@pytest.mark.asyncio
async def test_an_answer_that_fails_verification_counts_as_no_answer() -> None:
    """The anti-hallucination contract holds at the gate exactly as it does at
    drafting: a number whose sentence is not in the retrieved passage is thrown
    away, and the gate goes on enforcing the drafted figure."""
    gateway = FakeGateway([_chunk(PASSAGE_18, 0.9)])
    model = FakeModelGateway(
        LegalConstraintExtraction(
            min_bid_preparation_days=90,
            article_ref="Điều 45",
            source_quote="Thời gian chuẩn bị hồ sơ dự thầu tối thiểu là 90 ngày",
        )
    )

    assert await _nodes(gateway, model)._live_legal_minimum(_run_context(), "x") == (
        None,
        "not_available",
    )


@pytest.mark.asyncio
async def test_no_model_wired_means_no_figure_rather_than_a_crash() -> None:
    gateway = FakeGateway([_chunk(PASSAGE_18, 0.9)])

    assert await _nodes(gateway, None)._live_legal_minimum(_run_context(), "x") == (
        None,
        "not_available",
    )


# --- the retrieved law now reaches the prompt, not just the artifact ---------


class OrderRecordingGateway:
    """Records that it was asked, so call ORDER can be asserted."""

    def __init__(self, chunks: list[EvidenceChunk], log: list[str]) -> None:
        self.chunks = chunks
        self._log = log

    async def search(self, query: Any, context: Any) -> list[EvidenceChunk]:
        self._log.append("search")
        return self.chunks


class OrderRecordingModel:
    def __init__(self, result: Any, log: list[str]) -> None:
        self._result = result
        self._log = log
        self.variables: dict[str, Any] = {}

    async def generate_structured(self, request: Any, output_type: Any, *, run_context: Any) -> Any:
        self._log.append("model")
        self.variables = dict(request.variables)
        return self._result


@pytest.mark.asyncio
async def test_the_solicitation_prompt_actually_receives_the_law_it_retrieved() -> None:
    """The whole point of the reordering.

    Retrieval used to run AFTER the drafting call, so the passages could only
    ever be decoration on the artifact — the prompt had already been sent. An
    artifact carrying citations that never influenced a word of it reads, to an
    approver, exactly like one that was grounded.
    """
    log: list[str] = []
    knowledge = OrderRecordingGateway([_chunk(PASSAGE_18, 0.9)], log)
    model = OrderRecordingModel(
        SolicitationDraft(scope="Cung cấp màn hình.", technical_requirements=["Độ phân giải 4K"]),
        log,
    )

    draft = await _nodes(knowledge, model)._llm_solicitation(
        _run_context(), "goods", "đấu thầu rộng rãi", ["REQ-1"], [{"quote": PASSAGE_18}]
    )

    assert draft is not None
    assert "passages" in model.variables
    assert "18 ngày" in model.variables["passages"], "đoạn đã tra phải nằm trong prompt"
    assert model.variables["passages"].startswith("[1] "), "đánh số như bên bóc ràng buộc"


@pytest.mark.asyncio
async def test_the_criteria_prompt_receives_it_too() -> None:
    log: list[str] = []
    model = OrderRecordingModel(
        CriteriaDraft(
            weighted=[
                WeightedCriterion(code="W1", text="Kỹ thuật", weight=60),
                WeightedCriterion(code="W2", text="Giá", weight=40),
            ]
        ),
        log,
    )

    weighted = await _nodes(None, model)._llm_criteria(
        _run_context(), "goods", ["REQ-1"], [{"quote": PASSAGE_18}]
    )

    assert weighted and len(weighted) == 2
    assert "18 ngày" in model.variables["passages"]


@pytest.mark.asyncio
async def test_nothing_retrieved_still_drafts_rather_than_refusing() -> None:
    """Retrieval is grounding, not a gate — and the prompts say so in words.

    A package still has to be drafted when every provider is down. The empty
    string is the contract here: the prompt template renders, the model answers,
    and the deterministic fallbacks behind it are untouched.
    """
    log: list[str] = []
    model = OrderRecordingModel(
        SolicitationDraft(scope="Cung cấp màn hình.", technical_requirements=["4K"]), log
    )

    draft = await _nodes(None, model)._llm_solicitation(
        _run_context(), "goods", "đấu thầu rộng rãi", ["REQ-1"], []
    )

    assert draft is not None
    assert model.variables["passages"] == ""


@pytest.mark.asyncio
async def test_a_figure_read_off_the_shelf_is_not_reported_as_a_live_recheck() -> None:
    """The bug this second return value exists for, caught on a real run.

    Measured 2026-08-26: a full demo replay wrote ``live_min_days: 18`` onto the
    package while every web query had failed and the corpus fallback had
    answered. The figure was correct and the claim was false — the audit trail
    said the law had been re-checked against today's sources when it had been
    checked against a snapshot taken who-knows-when. That is worse than no
    re-check, because it is a re-check someone would rely on.

    Same three words the drafting step uses, read off the same evidence: a
    passage with no ``source_uri`` is one nobody can open, so it came off the
    shelf.
    """
    corpus_only = FakeGateway([_chunk(PASSAGE_18, 0.9)])  # không có source_uri
    model = FakeModelGateway(
        LegalConstraintExtraction(
            min_bid_preparation_days=18,
            article_ref="Điều 45 khoản 1",
            source_quote="Thời gian chuẩn bị hồ sơ dự thầu đối với đấu thầu rộng rãi trong "
            "nước tối thiểu là 18 ngày",
        )
    )

    days, source = await _nodes(corpus_only, model)._live_legal_minimum(_run_context(), "x")

    assert days == 18, "con số vẫn dùng được — bản lưu vẫn hơn không có gì"
    assert source == "indexed", "nhưng phải nói rõ nó đến từ bản lưu, không phải tra hôm nay"
