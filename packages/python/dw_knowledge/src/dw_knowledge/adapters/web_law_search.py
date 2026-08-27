"""Live legal retrieval: the open web instead of a pre-ingested corpus.

The law in a pre-ingested corpus is a photograph. It is right on the day it was
taken and quietly wrong afterwards, and nothing in the system knows which. This
adapter answers the same ``KnowledgeGatewayPort.search`` call by asking the web
at the moment the question is asked, so a package is drafted against whatever
is in force today rather than whatever was ingested last quarter.

Three things make that safe enough to put in front of a procurement decision.

**Only named sources count.** Anyone can rank a page saying the minimum bid
window is ninety days. Results outside the configured allowlist are dropped
BEFORE their content reaches the model — the allowlist is the fence, not a hint
to a model that is asked to be careful. An empty allowlist admits nothing.

**Passages, not snippets.** Search snippets are elided with "..." mid-sentence,
and ``verified_constraint`` requires the sentence a model quotes to appear
verbatim in a retrieved passage. Feeding it snippets would fail that check
almost every time and silently fall back to the deterministic default — the
feature would look wired and do nothing. So the pages themselves are fetched and
cut on sentence boundaries.

**Nothing downstream changes.** This implements the same port the Qdrant gateway
does, so the workflow nodes, the prompt and the anti-hallucination contract are
untouched. Swapping retrieval is a composition-root decision.

What is *generic* about all that — asking an engine, reading a page, not asking
twice — now lives in ``adapters/websearch/``. What stays here is the part that
only makes sense for law: which sources are trusted, which passage is worth
keeping, and how a passage becomes citable evidence.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path

import yaml

from dw_kernel.errors import InfrastructureError
from dw_kernel.ports import IdGenerator
from dw_knowledge.adapters.websearch.cache import TtlCache
from dw_knowledge.adapters.websearch.chain import FailoverSearchClient
from dw_knowledge.adapters.websearch.contracts import SearchHit, SearchParams
from dw_knowledge.adapters.websearch.fetch import (
    FetchedPage,
    FetchPolicy,
    PageFetcher,
    html_to_text,
)
from dw_knowledge.contracts import EvidenceChunk, EvidenceRef, SearchQuery
from dw_knowledge.ports import KnowledgeGatewayPort
from dw_platform.application.access_context import AccessContext

# Re-exported: the composition root and the tests reach for these by way of this
# module, and where a helper physically lives is not their business.
__all__ = [
    "DEFAULT_ROUTING",
    "FetchedPage",
    "LegalSourceConfig",
    "LegalSourceRouter",
    "PageFetcher",
    "SearchHit",
    "SearchParams",
    "TtlCache",
    "WebLawGateway",
    "allowed_hits",
    "html_to_text",
    "load_legal_sources",
    "passages",
]

logger = logging.getLogger("dw_knowledge.web_law")

# Stable namespace so the same URL always maps to the same source_document_id —
# the law watcher compares citations across runs and needs that identity to hold.
_URL_NAMESPACE = uuid.UUID("8f1d5a52-3c9e-5f77-9c31-000000000001")

# Web pages carry no clearance of their own. "internal" is the bottom of
# ``_CLASSIFICATION_LADDER``; anything outside the ladder is filtered out as
# unknown, so this is the only value that is actually readable.
_WEB_CLASSIFICATION = "internal"

_SENTENCE_END = re.compile(r"(?<=[.!?;])\s")
# What a 1.0 config meant by listing an anchor: legal pages repeat the anchor
# phrase in headings and cross-references, and requiring a day count kept those
# out. Still the right rule for the deadline question — see `anchor_requires`
# for why it stopped being the right rule for every question.
_LEGACY_ANCHOR_REQUIRE = r"\d+\s*ngày"

# 1.0 files predate failover; every key it lacks has a default that keeps
# the old single-provider behaviour.
_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})
_SITE_OPERATOR = re.compile(r"site:([^\s)]+)", re.IGNORECASE)


# ---------------------------------------------------------------- config --


def under(host: str, domain: str) -> bool:
    """Is ``host`` published by ``domain`` — the domain itself or below it.

    Measured 2026-08-26, and this was silently costing us the best sources.
    Matching hosts exactly meant three of the seven allowlisted domains could
    never match anything at all, because those organisations do not publish on
    their apex domain: the full text of the Procurement Law is on
    ``xaydungchinhsach.chinhphu.vn``, the legal database is on
    ``vbpl.moj.gov.vn``, and ``mpi.gov.vn`` answers on ``www.mpi.gov.vn`` — the
    ``www.`` alone was enough to fail. Search returned them, the allowlist
    dropped them, and the query came back thinner for it.

    The boundary is the leading dot, and it is the whole point: ``chinhphu.vn``
    admits ``xaydungchinhsach.chinhphu.vn`` and refuses ``evil-chinhphu.vn``.
    Comparing with ``endswith(domain)`` alone would admit both, which is how an
    allowlist turns into decoration.
    """
    host = host.lower().strip(".")
    domain = domain.lower().strip(".")
    return bool(domain) and (host == domain or host.endswith("." + domain))


@dataclass(frozen=True)
class LegalSourceConfig:
    """Versioned source policy (``configs/knowledge/legal_sources@*.yaml``)."""

    version: str
    allowed_domains: frozenset[str]
    preferred_order: tuple[str, ...]
    gl: str
    hl: str
    num: int
    site_bias: str
    context_terms: str
    max_bytes: int
    fetch_timeout_seconds: float
    max_pages_per_query: int
    accept_content_types: tuple[str, ...]
    window_chars: int
    max_passages_per_page: int
    anchors: tuple[str, ...]
    cache_ttl_seconds: int
    cache_max_entries: int
    # Which hosts to steer the engine toward. Not the same as the allowlist:
    # measured 2026-08-24, an OR over all seven collapsed to one site and the
    # query came back empty, so this is the short list that actually carries
    # statute text. The allowlist still filters whatever comes back.
    search_sites: tuple[str, ...] = ()
    # Provider names in the order they are tried. Empty means "serper only",
    # which is what every config written before failover existed asks for.
    providers: tuple[str, ...] = ()
    # Tavily tính tiền theo độ sâu: "basic" 1 credit, "advanced" 2. Mặc định
    # basic vì phần Tavily bóc đoạn hộ ta bị vứt đi — `passages()` tự cắt theo
    # ranh giới câu, vì `verified_constraint()` đòi câu model chép phải nằm
    # nguyên văn trong đoạn CHÍNH TA đưa cho nó. Thứ duy nhất cần ở Tavily là
    # `raw_content`. Nếu đo được rằng basic không trả `raw_content` thì đổi sang
    # advanced và ghi số đo kèm ngày vào config — đừng đoán.
    tavily_search_depth: str = "basic"
    exhausted_cooldown_seconds: float = 21_600.0
    advance_on_empty: bool = True
    # Which source answers which kind of question: "web", "corpus" or "both".
    # Empty keeps the built-in table, which is what pre-1.1 files describe.
    routing: Mapping[str, str] = field(default_factory=dict)
    corpus_fallback: bool = True
    # Anchor text -> a regex that a passage found by that anchor must ALSO
    # match. Absent means the anchor imposes nothing beyond being found.
    #
    # This used to be one global rule: every passage had to contain a day
    # count. That rule was written for the deadline question and it silently
    # governed the other three, so a query about evaluation criteria could
    # only ever return prose about deadlines — or nothing. Attaching the
    # requirement to the anchor puts it where the reasoning actually lives:
    # a hit on "thời gian chuẩn bị hồ sơ" with no number in it is a heading,
    # while a hit on "tiêu chí đánh giá" has no business carrying one.
    anchor_requires: Mapping[str, str] = field(default_factory=dict)

    def rank_of(self, host: str) -> int:
        """Position in ``preferred_order``; unlisted sources sort last.

        Matches subdomains for the same reason ``allows`` does — otherwise a
        source is admitted by the allowlist and then ranked as if it were a
        stranger, which is worse than either behaviour on its own.
        """
        for index, domain in enumerate(self.preferred_order):
            if under(host, domain):
                return index
        return len(self.preferred_order)

    def allows(self, host: str) -> bool:
        """Whether this host is published by one of the named sources."""
        return any(under(host, domain) for domain in self.allowed_domains)

    @property
    def fetch_policy(self) -> FetchPolicy:
        """The subset a page fetcher needs — it has no business with the rest."""
        return FetchPolicy(
            max_bytes=self.max_bytes,
            timeout_seconds=self.fetch_timeout_seconds,
            accept_content_types=self.accept_content_types,
        )


def load_legal_sources(path: Path) -> LegalSourceConfig:
    try:
        data = yaml.safe_load(path.read_bytes())
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise InfrastructureError(f"invalid legal source config: {path}") from exc
    if not isinstance(data, dict) or str(data.get("schema_version")) not in _SCHEMA_VERSIONS:
        raise InfrastructureError(f"unsupported legal source schema: {path}")
    search = data.get("search", {})
    fetch = data.get("fetch", {})
    passage = data.get("passage", {})
    cache = data.get("cache", {})
    return LegalSourceConfig(
        version=str(data.get("version", "0")),
        allowed_domains=frozenset(str(d).lower() for d in data.get("allowed_domains", [])),
        preferred_order=tuple(str(d).lower() for d in data.get("preferred_order", [])),
        gl=str(search.get("gl", "vn")),
        hl=str(search.get("hl", "vi")),
        num=int(search.get("num", 10)),
        site_bias=str(search.get("site_bias", "")),
        context_terms=str(search.get("context_terms", "")),
        max_bytes=int(fetch.get("max_bytes", 3_000_000)),
        fetch_timeout_seconds=float(fetch.get("timeout_seconds", 15)),
        max_pages_per_query=int(fetch.get("max_pages_per_query", 3)),
        accept_content_types=tuple(
            str(c).lower() for c in fetch.get("accept_content_types", ["text/html"])
        ),
        window_chars=int(passage.get("window_chars", 1200)),
        max_passages_per_page=int(passage.get("max_passages_per_page", 3)),
        anchors=_anchor_texts(passage.get("anchors", [])),
        anchor_requires=_anchor_requires(passage.get("anchors", [])),
        cache_ttl_seconds=int(cache.get("ttl_seconds", 86_400)),
        cache_max_entries=int(cache.get("max_entries", 512)),
        search_sites=_search_sites(search),
        providers=tuple(
            str(entry["name"])
            for entry in data.get("providers", [])
            if isinstance(entry, dict) and entry.get("name") and entry.get("enabled", True)
        ),
        tavily_search_depth=str(search.get("tavily_search_depth", "basic")),
        exhausted_cooldown_seconds=float(data.get("exhausted_cooldown_seconds", 21_600)),
        advance_on_empty=bool(data.get("advance_on_empty", True)),
        routing={
            str(domain): str(where).lower() for domain, where in (data.get("routing") or {}).items()
        },
    )


def _anchor_texts(raw: object) -> tuple[str, ...]:
    entries = raw if isinstance(raw, list) else []
    out: list[str] = []
    for entry in entries:
        text = entry.get("text") if isinstance(entry, dict) else entry
        if text:
            out.append(str(text).lower())
    return tuple(out)


def _anchor_requires(raw: object) -> dict[str, str]:
    """Per-anchor extra condition, with the pre-1.1 rule preserved.

    A bare string anchor means a 1.0 file, which applied the day-count rule to
    everything. Keeping that for bare strings is what lets the old config and
    the cross-package passage tests go on meaning what they meant.
    """
    entries = raw if isinstance(raw, list) else []
    out: dict[str, str] = {}
    for entry in entries:
        if isinstance(entry, dict):
            text, require = entry.get("text"), entry.get("require")
            if text and require:
                out[str(text).lower()] = str(require)
        elif entry:
            out[str(entry).lower()] = _LEGACY_ANCHOR_REQUIRE
    return out


def _search_sites(search: dict[str, object]) -> tuple[str, ...]:
    """Hosts to steer toward, from the modern key or the Google-flavoured one.

    Schema 1.0 spelled this as ``site_bias: "site:a OR site:b"`` — literal
    Google operator syntax sitting in shared config, which no other engine can
    honour. Reading it back out keeps those files working while the providers
    each render the host list their own way.
    """
    listed = search.get("sites")
    if isinstance(listed, list) and listed:
        return tuple(str(host).lower() for host in listed)
    return tuple(_SITE_OPERATOR.findall(str(search.get("site_bias", ""))))


# ----------------------------------------------------------------- search --


def allowed_hits(hits: list[SearchHit], config: LegalSourceConfig) -> list[SearchHit]:
    """Drop everything not published by a named source, best source first.

    Fails closed: with no allowlist configured nothing is admitted, because the
    alternative is to hand a procurement decision to whoever ranks highest.
    """
    kept = [hit for hit in hits if config.allows(hit.host)]
    return sorted(kept, key=lambda hit: (config.rank_of(hit.host), hit.position))


# --------------------------------------------------------------- passages --


def passages(text: str, config: LegalSourceConfig, query: str = "") -> list[str]:
    """Windows around anchor terms, cut on sentence boundaries.

    Whole sentences are the point. ``verified_constraint`` accepts a model's
    quote only when it appears verbatim in one of these, so a window that ends
    mid-sentence is a window the whole chain will reject.

    A window is kept only if it satisfies whatever the anchor that found it
    requires — see ``LegalSourceConfig.anchor_requires``.

    ``query`` decides which anchors get first refusal at the limited number of
    slots. Without it, selection falls back to document order, and on a full
    statute page that hands every slot to the definitions in the opening
    articles: measured 2026-08-25, asking about bid-preparation time returned
    three paragraphs defining "đấu thầu" and "bên mời thầu", with Điều 45
    nowhere in sight. Anchors whose wording appears in the question are tried
    first; when none do, every anchor competes as before.
    """
    lowered = text.lower()
    asked = query.casefold()
    relevant = [a for a in config.anchors if a in asked]
    anchors = relevant or list(config.anchors)

    starts: list[tuple[int, int, str]] = []
    for rank, anchor in enumerate(anchors):
        # Capped PER ANCHOR, not across all of them. A single global cap meant
        # the anchors listed first ate every candidate slot on a long statute
        # page, so a question about evaluation criteria could be answered
        # entirely out of the paragraphs about open tendering.
        found = 0
        position = lowered.find(anchor)
        while position != -1 and found < config.max_passages_per_page * 2:
            starts.append((rank, position, anchor))
            found += 1
            position = lowered.find(anchor, position + len(anchor))
    if not starts:
        return []

    half = max(config.window_chars // 2, 100)
    out: list[str] = []
    used: list[tuple[int, int]] = []
    for _rank, hit, anchor in sorted(starts):
        left = _sentence_start(text, max(0, hit - half))
        right = _sentence_end(text, min(len(text), hit + half))
        if any(left < end and start < right for start, end in used):
            continue  # already covered by an earlier window
        chunk = " ".join(text[left:right].split())
        if len(chunk) >= 80 and _satisfies(chunk, config.anchor_requires.get(anchor)):
            out.append(chunk)
            used.append((left, right))
        if len(out) >= config.max_passages_per_page:
            break
    return out


def _satisfies(chunk: str, pattern: str | None) -> bool:
    return pattern is None or re.search(pattern, chunk, re.IGNORECASE) is not None


def _sentence_start(text: str, index: int) -> int:
    if index <= 0:
        return 0
    window = text[max(0, index - 400) : index]
    matches = list(_SENTENCE_END.finditer(window))
    return max(0, index - 400) + matches[-1].end() if matches else index


def _sentence_end(text: str, index: int) -> int:
    if index >= len(text):
        return len(text)
    window = text[index : index + 400]
    match = _SENTENCE_END.search(window)
    return index + match.end() if match else index


# ---------------------------------------------------------------- gateway --


@dataclass
class WebLawGateway:
    """Implements ``KnowledgeGatewayPort`` against live web sources."""

    client: FailoverSearchClient
    fetcher: PageFetcher
    config: LegalSourceConfig
    id_generator: IdGenerator
    cache: TtlCache | None = None

    def _cache_key(self, context: AccessContext, query: SearchQuery) -> str:
        """Tenant-scoped, because the query text carries case figures.

        ``top_k`` is deliberately absent. It used to be part of the key while
        the entry stored the unsliced list, so two callers asking the same
        question at different depths paid for two searches to hold two copies
        of one answer. The slice happens on read instead — and a cache whose
        whole job is to save quota should not miss on a detail like that.
        """
        return f"{context.tenant_id}|{query.domain}|{' '.join(query.text.split()).casefold()}"

    async def search(self, query: SearchQuery, context: AccessContext) -> list[EvidenceChunk]:
        started = time.monotonic()
        cache_key = self._cache_key(context, query)
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                logger.info('web law: "%s" — từ cache, %d đoạn', _short(query.text), len(cached))
                return cached[: query.top_k]

        params = SearchParams(
            query=" ".join(part for part in (query.text, self.config.context_terms) if part),
            country=self.config.gl,
            language=self.config.hl,
            count=self.config.num,
            sites=self.config.search_sites,
        )
        # The allowlist runs INSIDE the chain, not after it: a provider that
        # returns ten results from ten sources we do not trust has given us
        # nothing, and only the chain can act on that by asking the next one.
        hits, provider = await self.client.search(
            params, accept=lambda found: allowed_hits(found, self.config)
        )

        chunks: list[EvidenceChunk] = []
        # One line per source, so "which sites did it read?" has an answer that
        # does not require turning on debug logging or reading the database.
        trace: list[str] = []
        for hit in hits[: self.config.max_pages_per_query]:
            page = self._page_for(hit, provider)
            if page is None:
                page = await self.fetcher.fetch(hit.url)
            if page is None:
                trace.append(f"{hit.host} ✗không đọc được")
                continue
            found = passages(page.text, self.config, query.text)
            trace.append(f"{hit.host} {'✓' if found else '✗'}{len(found)} đoạn")
            for text in found:
                chunks.append(self._to_chunk(text, page, hit))
                if len(chunks) >= query.top_k:
                    break
            if len(chunks) >= query.top_k:
                break

        result = [
            chunk for chunk in chunks if chunk.evidence.relevance_score >= query.min_relevance
        ]
        logger.info(
            'web law: "%s" qua %s → %d qua allowlist [%s] %d đoạn dùng được, %.1fs',
            _short(query.text),
            provider,
            len(hits),
            ", ".join(trace) or "không tải trang nào",
            len(result),
            time.monotonic() - started,
        )
        if self.cache is not None:
            self.cache.put(cache_key, result)
        return result[: query.top_k]

    @staticmethod
    def _page_for(hit: SearchHit, provider: str) -> FetchedPage | None:
        """Use the body the provider already sent, when it sent one.

        Tavily returns page text with the result. Fetching that URL again would
        be a second round trip for text we hold — and for a source that renders
        with JavaScript it is the difference between a passage and an empty
        shell. The version label names the provider rather than a Last-Modified
        header, because we never saw the response headers for this one.
        """
        if not hit.content:
            return None
        return FetchedPage(url=hit.url, text=hit.content, source_version=f"web:{provider}")

    @staticmethod
    def _label(hit: SearchHit) -> str:
        """What a reader sees as the source name.

        The host is part of it, always: "Điều 45 Luật Đấu thầu" tells nobody
        whether this came from a government portal or a content farm, and that
        judgement is the reader's to make.
        """
        title = " ".join(hit.title.split())[:120]
        return f"{title} — {hit.host}" if title else hit.host

    def _to_chunk(self, text: str, page: FetchedPage, hit: SearchHit) -> EvidenceChunk:
        return EvidenceChunk(
            content=text,
            evidence=EvidenceRef(
                evidence_id=self.id_generator.new_uuid(),
                # Deterministic per URL: the watcher compares citations between
                # runs, so the same page must keep the same identity.
                source_document_id=uuid.uuid5(_URL_NAMESPACE, page.url),
                source_version=page.source_version,
                quote=text[:280],
                source_title=self._label(hit),
                source_uri=page.url,
                relevance_score=_score(hit, self.config),
                classification=_WEB_CLASSIFICATION,
                provenance_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            ),
        )


def _short(text: str, limit: int = 60) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _score(hit: SearchHit, config: LegalSourceConfig) -> float:
    """Rank-based score: source trust first, then the engine's ordering."""
    source_penalty = config.rank_of(hit.host) * 0.05
    rank_penalty = min(max(hit.position - 1, 0), 9) * 0.03
    return round(max(0.0, min(1.0, 1.0 - source_penalty - rank_penalty)), 4)


# What answers what, when config says nothing. Same table the frozensets used
# to encode, in one readable place instead of three defaulted fields.
DEFAULT_ROUTING: Mapping[str, str] = {"legal": "web", "shared": "both"}


@dataclass
class LegalSourceRouter:
    """Decides, per question, whether the answer can be older than today.

    Three destinations, and the middle one is the reason this is not a one-liner:

    ``web`` — the drafting node asking about a statute. Live search, because a
    photograph of the law is right on the day it was taken and quietly wrong
    afterwards.

    ``both`` — a person in chat. They do not know the corpus is filed into
    legal/policy/tender and should not have to; the gateway reads their domain
    as "no predicate", so the question could be about the law OR about company
    policy. Both are searched and interleaved. Appending web after corpus would
    be simpler and useless: the corpus fills ``top_k`` and the live results
    never reach the model.

    ``corpus`` — everything else. Internal procurement rules are not on Google,
    and looking for them there spends a search credit to find someone else's.

    The table is configuration (``routing:`` in the source policy) rather than
    three sets of domain names buried in field defaults, because "which
    questions leave the building" is a decision someone should be able to read
    without opening this file.
    """

    inner: KnowledgeGatewayPort
    web: KnowledgeGatewayPort | None = None
    routing: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_ROUTING))
    # Whether a live lookup that comes back with nothing may be answered from
    # the ingested corpus instead. The corpus is a photograph, so this trades
    # "possibly out of date" against "no legal grounding at all" — and the
    # caller is told which it got, via evidence that carries no source_uri.
    corpus_fallback: bool = True
    # Anchor text -> a regex that a passage found by that anchor must ALSO
    # match. Absent means the anchor imposes nothing beyond being found.
    #
    # This used to be one global rule: every passage had to contain a day
    # count. That rule was written for the deadline question and it silently
    # governed the other three, so a query about evaluation criteria could
    # only ever return prose about deadlines — or nothing. Attaching the
    # requirement to the anchor puts it where the reasoning actually lives:
    # a hit on "thời gian chuẩn bị hồ sơ" with no number in it is a heading,
    # while a hit on "tiêu chí đánh giá" has no business carrying one.
    anchor_requires: Mapping[str, str] = field(default_factory=dict)

    def _where(self, domain: str) -> str:
        return self.routing.get(domain, "corpus")

    async def search(self, query: SearchQuery, context: AccessContext) -> list[EvidenceChunk]:
        if self.web is None:
            return await self.inner.search(query, context)
        where = self._where(query.domain)
        if where == "corpus":
            return await self.inner.search(query, context)

        if where == "web":
            try:
                live = await self.web.search(query, context)
            except Exception:
                live = []
                logger.warning("web law: tra trực tuyến thất bại", exc_info=True)
            if live or not self.corpus_fallback:
                return live
            # Loud on purpose. The package will be drafted from an indexed copy
            # of the law with no indication in the evidence itself that it is
            # older than today — the only other signal is the absence of a
            # source URL, which nobody reads a log for.
            logger.warning(
                "web law: không tra được nguồn trực tuyến nào — "
                "trả lời bằng corpus đã ingest (căn cứ có thể cũ)"
            )
            return await self.inner.search(query, context)

        corpus = await self.inner.search(query, context)
        try:
            live = await self.web.search(query, context)
        except Exception:
            # Retrieval is grounding, not a gate. Losing the live half must not
            # take the corpus answer down with it.
            logger.warning("web law: truy vấn thất bại, chỉ dùng corpus", exc_info=True)
            live = []
        return _interleave(corpus, live)[: query.top_k]

    async def list_documents(self, *args: object, **kwargs: object) -> object:
        """Delegated so citation titles keep resolving.

        ``ConversationIntakeService`` builds its document-title map only when the
        gateway offers this; without it every internal citation degrades to the
        word "tài liệu" — including the ones that have nothing to do with the web.
        """
        return await self.inner.list_documents(*args, **kwargs)  # type: ignore[attr-defined]


def _interleave(first: list[EvidenceChunk], second: list[EvidenceChunk]) -> list[EvidenceChunk]:
    """Alternate, longest tail last — neither source can crowd the other out."""
    merged: list[EvidenceChunk] = []
    for a, b in zip_longest(first, second):
        if a is not None:
            merged.append(a)
        if b is not None:
            merged.append(b)
    return merged
