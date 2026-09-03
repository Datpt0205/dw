"""Web-backed legal retrieval: the fence, the passages, and the routing.

No network here. The provider adapters and ``PageFetcher`` are the only pieces
that touch HTTP, and both are replaced by fakes — what is worth pinning is the logic
that decides which sources count, what a passage looks like when it reaches the
anti-hallucination check, and which questions are allowed to leave the building
at all.
"""

import uuid

import pytest

from dw_kernel.ports import SequentialIdGenerator
from dw_knowledge.adapters.web_law_search import (
    FetchedPage,
    LegalSourceConfig,
    LegalSourceRouter,
    SearchHit,
    SearchParams,
    TtlCache,
    WebLawGateway,
    allowed_hits,
    html_to_text,
    passages,
    under,
)
from dw_knowledge.adapters.websearch.chain import FailoverSearchClient
from dw_knowledge.contracts import EvidenceChunk, EvidenceRef, SearchQuery
from dw_platform.application.access_context import AccessContext

pytestmark = pytest.mark.unit


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


def make_config(**overrides: object) -> LegalSourceConfig:
    defaults: dict[str, object] = {
        "version": "1.0.0",
        "allowed_domains": frozenset({"vanban.chinhphu.vn", "thuvienphapluat.vn"}),
        "preferred_order": ("vanban.chinhphu.vn", "thuvienphapluat.vn"),
        "gl": "vn",
        "hl": "vi",
        "num": 10,
        "site_bias": "",
        "context_terms": "luật đấu thầu",
        "max_bytes": 3_000_000,
        "fetch_timeout_seconds": 15.0,
        "max_pages_per_query": 3,
        "accept_content_types": ("text/html",),
        "window_chars": 1200,
        "max_passages_per_page": 3,
        "anchors": ("thời gian chuẩn bị hồ sơ",),
        "cache_ttl_seconds": 3600,
        "cache_max_entries": 8,
    }
    defaults.update(overrides)
    return LegalSourceConfig(**defaults)  # type: ignore[arg-type]


def hit(url: str, position: int = 1) -> SearchHit:
    return SearchHit(title="t", url=url, snippet="s", position=position)


# --- the fence --------------------------------------------------------------


def test_results_outside_the_allowlist_never_reach_the_caller() -> None:
    config = make_config()
    kept = allowed_hits(
        [
            hit("https://seo-farm.example/luat-dau-thau", 1),
            hit("https://vanban.chinhphu.vn/dieu-45", 4),
        ],
        config,
    )
    assert [h.host for h in kept] == ["vanban.chinhphu.vn"]


def test_empty_allowlist_admits_nothing() -> None:
    """Fail closed: a missing list is not an open door."""
    config = make_config(allowed_domains=frozenset(), preferred_order=())
    assert allowed_hits([hit("https://vanban.chinhphu.vn/x")], config) == []


def test_official_source_outranks_an_aggregator_that_google_put_first() -> None:
    config = make_config()
    kept = allowed_hits(
        [hit("https://thuvienphapluat.vn/a", 1), hit("https://vanban.chinhphu.vn/b", 7)],
        config,
    )
    assert [h.host for h in kept] == ["vanban.chinhphu.vn", "thuvienphapluat.vn"]


def test_a_source_publishes_from_its_subdomains_and_the_allowlist_knows_it() -> None:
    """Measured 2026-08-26: three of seven allowlisted domains matched nothing.

    Government bodies do not publish on their apex domain. The full text of the
    Procurement Law is served from ``xaydungchinhsach.chinhphu.vn``; matching
    hosts exactly meant search found it, the allowlist threw it away, and the
    query came back with the aggregator's summary articles instead. Measured on
    the three real question shapes, admitting subdomains took the passage yield
    from 0/0/1 to 3/6/4.
    """
    config = make_config(
        allowed_domains=frozenset({"chinhphu.vn"}), preferred_order=("chinhphu.vn",)
    )

    kept = allowed_hits([hit("https://xaydungchinhsach.chinhphu.vn/toan-van-luat")], config)

    assert [h.host for h in kept] == ["xaydungchinhsach.chinhphu.vn"]


def test_the_dot_is_the_fence_and_a_lookalike_domain_does_not_get_over_it() -> None:
    """The failure mode that makes an allowlist decoration.

    ``endswith("chinhphu.vn")`` is true of ``evil-chinhphu.vn``, and anyone can
    register that. Requiring the leading dot is what separates "published by
    this source" from "spelled like it".
    """
    config = make_config(allowed_domains=frozenset({"chinhphu.vn"}), preferred_order=())

    assert allowed_hits([hit("https://evil-chinhphu.vn/dieu-45")], config) == []
    assert under("xaydungchinhsach.chinhphu.vn", "chinhphu.vn")
    assert not under("evil-chinhphu.vn", "chinhphu.vn")
    assert not under("chinhphu.vn.attacker.example", "chinhphu.vn")


def test_a_subdomain_is_ranked_as_the_source_it_belongs_to() -> None:
    """Admitting a host and then ranking it as a stranger is worse than either.

    Without this the government's own full-text page sorted below an
    aggregator's news article, because ``rank_of`` did not recognise it — which
    is exactly what happened in the 2026-08-26 measurement.
    """
    config = make_config(
        allowed_domains=frozenset({"chinhphu.vn", "luatvietnam.vn"}),
        preferred_order=("chinhphu.vn", "luatvietnam.vn"),
    )

    kept = allowed_hits(
        [
            hit("https://luatvietnam.vn/tin-tuc", 1),
            hit("https://xaydungchinhsach.chinhphu.vn/x", 2),
        ],
        config,
    )

    assert [h.host for h in kept] == ["xaydungchinhsach.chinhphu.vn", "luatvietnam.vn"]


# --- html + passages --------------------------------------------------------


def test_script_and_style_content_is_not_text() -> None:
    html = (
        "<html><head><style>.a{color:red}</style><script>var x=1;</script></head>"
        "<body><p>Điều 45.</p><p>Thời gian&nbsp;chuẩn bị.</p></body></html>"
    )
    text = html_to_text(html)
    assert "color:red" not in text
    assert "var x" not in text
    assert "Điều 45." in text
    assert "Thời gian chuẩn bị." in text


def test_passage_keeps_the_whole_sentence_around_the_anchor() -> None:
    """A window cut mid-sentence is a window the quote check will reject.

    The end-to-end join with ``verified_constraint`` is pinned on the tender
    side (``test_web_passages_feed_the_legal_check``), where that dependency
    direction is allowed.
    """
    sentence = (
        "Thời gian chuẩn bị hồ sơ dự thầu đối với đấu thầu rộng rãi trong nước "
        "tối thiểu là 18 ngày, kể từ ngày đầu tiên hồ sơ mời thầu được phát hành."
    )
    page = ("Mở đầu không liên quan. " * 30) + sentence + (" Phần sau cũng dài dòng." * 30)

    found = passages(page, make_config())

    assert found, "anchor present but no passage produced"
    assert sentence in found[0]


def test_no_anchor_means_no_passage() -> None:
    assert passages("Một trang nói về chuyện khác hoàn toàn.", make_config()) == []


def test_overlapping_anchor_hits_do_not_produce_duplicate_passages() -> None:
    config = make_config(window_chars=400)
    text = "A. " * 20 + "thời gian chuẩn bị hồ sơ là 18 ngày. " * 3 + "B. " * 20
    assert len(passages(text, config)) == 1


# --- gateway ----------------------------------------------------------------


class FakeProvider:
    """One search engine, standing in for whichever real one is first."""

    def __init__(self, hits: list[SearchHit], name: str = "fake") -> None:
        self._hits = hits
        self.calls = 0
        self._name = name

    @property
    def provider_name(self) -> str:
        return self._name

    async def search(self, params: SearchParams) -> list[SearchHit]:
        self.calls += 1
        return self._hits


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages
        self.fetched: list[str] = []

    async def fetch(self, url: str) -> FetchedPage | None:
        self.fetched.append(url)
        text = self._pages.get(url)
        return None if text is None else FetchedPage(url, text, "web:2026-08-24")


PAGE = (
    "Điều 45. "
    + ("nội dung. " * 20)
    + "Thời gian chuẩn bị hồ sơ dự thầu tối thiểu là 18 ngày. "
    + ("phần sau. " * 20)
)


def build_gateway(**overrides: object) -> tuple[WebLawGateway, FakeProvider, FakeFetcher]:
    config = make_config(**overrides)
    provider = FakeProvider([hit("https://vanban.chinhphu.vn/dieu-45")])
    fetcher = FakeFetcher({"https://vanban.chinhphu.vn/dieu-45": PAGE})
    gateway = WebLawGateway(
        client=FailoverSearchClient(providers=[provider]),
        fetcher=fetcher,  # type: ignore[arg-type]
        config=config,
        id_generator=SequentialIdGenerator(),
        cache=TtlCache(config.cache_ttl_seconds, config.cache_max_entries),
    )
    return gateway, provider, fetcher


@pytest.mark.asyncio
async def test_evidence_satisfies_the_contract_the_rest_of_the_system_expects() -> None:
    gateway, _, _ = build_gateway()

    chunks = await gateway.search(
        SearchQuery(text="thời gian chuẩn bị", domain="legal"), make_context()
    )

    assert chunks
    ref: EvidenceRef = chunks[0].evidence
    assert len(ref.provenance_hash) == 64
    # "internal" is the only classification the clearance ladder can read; a
    # value like "public" would be filtered out as unknown.
    assert ref.classification == "internal"
    assert 0.0 <= ref.relevance_score <= 1.0
    assert ref.source_version == "web:2026-08-24"


@pytest.mark.asyncio
async def test_same_url_always_gets_the_same_document_id() -> None:
    """The watcher compares citations between runs; identity must be stable."""
    first, _, _ = build_gateway()
    second, _, _ = build_gateway()
    query = SearchQuery(text="thời gian chuẩn bị", domain="legal")

    a = await first.search(query, make_context())
    b = await second.search(query, make_context())

    assert a[0].evidence.source_document_id == b[0].evidence.source_document_id


@pytest.mark.asyncio
async def test_unreachable_page_is_skipped_not_fatal() -> None:
    config = make_config()
    gateway = WebLawGateway(
        client=FailoverSearchClient(
            providers=[
                FakeProvider(
                    [
                        hit("https://vanban.chinhphu.vn/gone", 1),
                        hit("https://thuvienphapluat.vn/ok", 2),
                    ]
                )
            ]
        ),
        fetcher=FakeFetcher({"https://thuvienphapluat.vn/ok": PAGE}),  # type: ignore[arg-type]
        config=config,
        id_generator=SequentialIdGenerator(),
    )

    chunks = await gateway.search(
        SearchQuery(text="thời gian chuẩn bị", domain="legal"), make_context()
    )

    assert chunks and "18 ngày" in chunks[0].content


@pytest.mark.asyncio
async def test_repeat_query_is_served_from_cache() -> None:
    """Every free tier is finite; drafting must not spend two calls on one answer."""
    gateway, provider, _ = build_gateway()
    query = SearchQuery(text="thời gian chuẩn bị", domain="legal")
    context = make_context()

    await gateway.search(query, context)
    await gateway.search(query, context)

    assert provider.calls == 1


@pytest.mark.asyncio
async def test_another_tenant_does_not_read_this_tenants_cache_entry() -> None:
    gateway, provider, _ = build_gateway()
    query = SearchQuery(text="hạn mức phê duyệt 300.000.000.000", domain="legal")

    await gateway.search(query, make_context())
    await gateway.search(query, make_context())

    assert provider.calls == 2


# --- routing ----------------------------------------------------------------


class RecordingGateway:
    def __init__(self, label: str, chunks: list[EvidenceChunk] | None = None) -> None:
        self.label = label
        self.domains: list[str] = []
        self._chunks = chunks or []

    async def search(self, query: SearchQuery, context: AccessContext) -> list[EvidenceChunk]:
        self.domains.append(query.domain)
        return list(self._chunks)


@pytest.mark.asyncio
async def test_internal_policy_never_leaves_for_the_web() -> None:
    """Company procurement rules are not on Google, and must not be looked for.

    ``shared`` is chat, which spans both sources (a person does not know the
    corpus is filed by domain). ``policy`` is an explicit ask for internal
    rules — searching the web for those spends a credit to find someone else's.
    """
    corpus, web = RecordingGateway("qdrant"), RecordingGateway("web", [_chunk("web-1")])
    router = LegalSourceRouter(inner=corpus, web=web)
    context = make_context()

    await router.search(SearchQuery(text="hạn mức phê duyệt", domain="policy"), context)
    await router.search(SearchQuery(text="thời gian chuẩn bị", domain="legal"), context)
    await router.search(SearchQuery(text="mẫu hồ sơ", domain="tender"), context)

    assert web.domains == ["legal"]
    assert corpus.domains == ["policy", "tender"]


@pytest.mark.asyncio
async def test_the_routing_table_comes_from_config_not_from_this_code() -> None:
    """Which questions leave the building is a decision someone reads, not greps.

    Flipping ``legal`` to the corpus is the switch you want during an incident —
    a spent quota, a source that started serving nonsense — and it should not
    need a deploy.
    """
    corpus, web = RecordingGateway("qdrant"), RecordingGateway("web", [_chunk("web-1")])
    router = LegalSourceRouter(inner=corpus, web=web, routing={"legal": "corpus", "policy": "web"})
    context = make_context()

    await router.search(SearchQuery(text="thời gian chuẩn bị", domain="legal"), context)
    await router.search(SearchQuery(text="hạn mức", domain="policy"), context)

    assert corpus.domains == ["legal"] and web.domains == ["policy"]


@pytest.mark.asyncio
async def test_a_live_lookup_that_finds_nothing_falls_back_to_the_indexed_copy() -> None:
    """Stale law beats no law — but only because the caller can tell which it got.

    Evidence from the corpus carries no ``source_uri``; that absence is the
    signal the drafting node reads to mark the package as grounded on an
    indexed copy rather than on today's sources.
    """
    corpus = RecordingGateway("qdrant", [_chunk("corpus-1")])
    web = RecordingGateway("web")  # trả rỗng: cả chuỗi provider không ra gì
    router = LegalSourceRouter(inner=corpus, web=web)

    chunks = await router.search(
        SearchQuery(text="thời gian chuẩn bị", domain="legal"), make_context()
    )

    assert [c.content for c in chunks] == ["corpus-1"]
    assert corpus.domains == ["legal"]
    assert chunks[0].evidence.source_uri is None, "dấu hiệu để bên soạn biết căn cứ là bản lưu"


@pytest.mark.asyncio
async def test_the_fallback_can_be_refused_so_silence_stays_silence() -> None:
    """Some deployments would rather draft with no citation than with an old one."""
    corpus = RecordingGateway("qdrant", [_chunk("corpus-1")])
    router = LegalSourceRouter(inner=corpus, web=RecordingGateway("web"), corpus_fallback=False)

    chunks = await router.search(
        SearchQuery(text="thời gian chuẩn bị", domain="legal"), make_context()
    )

    assert chunks == [] and corpus.domains == []


@pytest.mark.asyncio
async def test_without_a_web_gateway_everything_falls_back_to_the_corpus() -> None:
    corpus = RecordingGateway("qdrant")
    router = LegalSourceRouter(inner=corpus, web=None)

    await router.search(SearchQuery(text="x", domain="legal"), make_context())

    assert corpus.domains == ["legal"]


# --- provenance ------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_carries_a_source_a_reader_can_follow() -> None:
    """A legal answer nobody can go and check is an assertion, not a citation."""
    gateway, _, _ = build_gateway()

    chunks = await gateway.search(
        SearchQuery(text="thời gian chuẩn bị", domain="legal"), make_context()
    )

    ref = chunks[0].evidence
    assert ref.source_uri == "https://vanban.chinhphu.vn/dieu-45"
    # The host is part of the name: a title alone does not tell the reader
    # whether this is a government portal or a content farm.
    assert ref.source_title is not None and "vanban.chinhphu.vn" in ref.source_title


def test_aspnet_pages_are_not_emptied_by_the_form_wrapper() -> None:
    """WebForms wraps the whole body in one <form>; skipping it loses the page.

    Measured 2026-08-24: vanban.chinhphu.vn dropped from 5,809 characters to 48
    when <form> was in the skip set.
    """
    html = (
        "<html><body><form method='post' action='x'>"
        "<p>Điều 45. Thời gian chuẩn bị hồ sơ dự thầu tối thiểu là 18 ngày.</p>"
        "<button>Tìm kiếm</button></form></body></html>"
    )

    text = html_to_text(html)

    assert "tối thiểu là 18 ngày" in text
    assert "Tìm kiếm" not in text  # the control itself is still chrome


# --- routing: chat spans both sources --------------------------------------


class StubGateway:
    def __init__(self, chunks: list[EvidenceChunk]) -> None:
        self._chunks = chunks
        self.domains: list[str] = []

    async def search(self, query: SearchQuery, context: AccessContext) -> list[EvidenceChunk]:
        self.domains.append(query.domain)
        return self._chunks

    async def list_documents(self, *args: object, **kwargs: object) -> str:
        return "delegated"


def _chunk(marker: str) -> EvidenceChunk:
    return EvidenceChunk(
        content=marker,
        evidence=EvidenceRef(
            evidence_id=uuid.uuid4(),
            source_document_id=uuid.uuid4(),
            source_version="v",
            relevance_score=0.5,
            classification="internal",
            provenance_hash="a" * 64,
        ),
    )


@pytest.mark.asyncio
async def test_a_chat_question_reaches_both_the_corpus_and_the_web() -> None:
    """Chat asks with domain="shared" — the person does not know the shelves.

    Before this, "shared" fell through to the corpus and live search was never
    consulted from chat at all.
    """
    corpus = StubGateway([_chunk("corpus-1"), _chunk("corpus-2")])
    web = StubGateway([_chunk("web-1"), _chunk("web-2")])
    router = LegalSourceRouter(inner=corpus, web=web)

    got = await router.search(
        SearchQuery(text="bao nhiêu ngày?", domain="shared", top_k=4), make_context()
    )

    assert [c.content for c in got] == ["corpus-1", "web-1", "corpus-2", "web-2"]


@pytest.mark.asyncio
async def test_the_corpus_cannot_crowd_the_live_results_out() -> None:
    """Appending instead of interleaving would fill top_k and hide the web half."""
    corpus = StubGateway([_chunk(f"corpus-{i}") for i in range(5)])
    web = StubGateway([_chunk("web-1")])
    router = LegalSourceRouter(inner=corpus, web=web)

    got = await router.search(SearchQuery(text="x", domain="shared", top_k=3), make_context())

    assert "web-1" in [c.content for c in got]


@pytest.mark.asyncio
async def test_a_failed_web_lookup_does_not_take_the_corpus_answer_with_it() -> None:
    class Broken:
        async def search(self, query: SearchQuery, context: AccessContext) -> list[EvidenceChunk]:
            raise RuntimeError("web search down")

    corpus = StubGateway([_chunk("corpus-1")])
    router = LegalSourceRouter(inner=corpus, web=Broken())

    got = await router.search(SearchQuery(text="x", domain="shared"), make_context())

    assert [c.content for c in got] == ["corpus-1"]


@pytest.mark.asyncio
async def test_list_documents_is_delegated_so_titles_keep_resolving() -> None:
    """Without this every INTERNAL citation degrades to the word "tài liệu"."""
    router = LegalSourceRouter(inner=StubGateway([]), web=StubGateway([]))

    assert await router.list_documents() == "delegated"


# --- passages: the rule belongs to the anchor, not to every question ---------


def test_an_anchor_that_asks_for_nothing_extra_keeps_prose_without_numbers() -> None:
    """Why the day-count rule stopped being global.

    Four legal queries run during drafting and only one of them is about a
    deadline. While the rule applied to all of them, the query about evaluation
    criteria could return prose about deadlines or nothing at all — never the
    criteria it asked for, which is a feature that looks wired and does nothing.
    """
    page = (
        "Tiêu chí đánh giá hồ sơ dự thầu gồm tiêu chí về năng lực, kinh nghiệm, "
        "kỹ thuật và giá. " + ("nội dung khác. " * 30)
    )
    config = make_config(anchors=("tiêu chí đánh giá",), anchor_requires={})

    found = passages(page, config)

    assert found and "Tiêu chí đánh giá" in found[0]


def test_the_deadline_anchor_still_refuses_a_heading_with_no_number_in_it() -> None:
    """The original rule, kept where it was right: statute pages repeat the
    phrase in headings and cross-references, and a heading yields no sentence
    ``verified_constraint`` can check a number against."""
    page = "Thời gian chuẩn bị hồ sơ dự thầu. " + ("mục lục. " * 40)
    config = make_config(
        anchors=("thời gian chuẩn bị hồ sơ",),
        anchor_requires={"thời gian chuẩn bị hồ sơ": r"\d+\s*ngày"},
    )

    assert passages(page, config) == []


def test_one_anchor_cannot_eat_every_candidate_slot_from_the_others() -> None:
    """A single global cap made anchor order decide the answer.

    On a long statute page the anchors listed first filled the candidate list
    before the later ones were ever scanned, so a question about criteria was
    answered out of the paragraphs about open tendering.
    """
    page = (
        ("Đấu thầu rộng rãi được áp dụng như sau. " + ("nội dung. " * 12)) * 8
        + "Tiêu chí đánh giá hồ sơ dự thầu gồm năng lực và kinh nghiệm. "
        + ("phần cuối. " * 20)
    )
    config = make_config(
        anchors=("đấu thầu rộng rãi", "tiêu chí đánh giá"),
        anchor_requires={},
        max_passages_per_page=10,
    )

    found = passages(page, config)

    assert any("Tiêu chí đánh giá" in chunk for chunk in found)


def test_the_question_decides_which_anchors_get_the_limited_slots() -> None:
    """Measured on a live statute page, 2026-08-25, and it was wrong.

    A full Luật Đấu thầu page opens with definitions and reaches Điều 45 much
    later. Selecting windows by document position handed all three slots to
    paragraphs defining "đấu thầu" and "bên mời thầu", and the question about
    bid-preparation time came back with no day count anywhere in it — which
    downstream is indistinguishable from "the law does not say".
    """
    page = (
        "Đấu thầu rộng rãi là hình thức lựa chọn nhà thầu không hạn chế số lượng "
        "nhà thầu tham dự. "
        + ("nội dung định nghĩa. " * 40)
        + "Thời gian chuẩn bị hồ sơ dự thầu tối thiểu là 18 ngày kể từ ngày phát hành. "
        + ("phần sau. " * 20)
    )
    config = make_config(
        anchors=("thời gian chuẩn bị hồ sơ", "đấu thầu rộng rãi"),
        anchor_requires={"thời gian chuẩn bị hồ sơ": r"\d+\s*ngày"},
        max_passages_per_page=1,
    )

    found = passages(page, config, "thời gian chuẩn bị hồ sơ dự thầu tối thiểu")

    assert found and "18 ngày" in found[0], "câu hỏi về mốc thời gian phải ra đoạn có mốc"


def test_a_question_matching_no_anchor_still_gets_whatever_the_page_offers() -> None:
    """Fallback, not failure: an unfamiliar question is not a reason to return
    nothing when the page plainly carries relevant provisions."""
    page = "Đấu thầu rộng rãi là hình thức lựa chọn nhà thầu. " + ("nội dung. " * 30)
    config = make_config(anchors=("đấu thầu rộng rãi",), anchor_requires={})

    assert passages(page, config, "một câu hỏi không khớp neo nào")
