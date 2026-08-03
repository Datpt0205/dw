"""Retrieval evaluation harness (recall@k / precision@k / MRR).

Pure metric computation over a golden set: a query and the set of document ids
that *should* be retrieved. Decoupled from any store — pass a ``search`` callable
(the knowledge gateway in prod, an in-memory fake in tests) so the harness runs
in CI without infra and against live Qdrant+TEI in a smoke suite.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RetrievalCase:
    """One golden query and the document ids that are relevant to it."""

    query: str
    domain: str
    relevant_document_ids: frozenset[UUID]


@dataclass(frozen=True)
class CaseResult:
    query: str
    recall: float
    precision: float
    reciprocal_rank: float
    retrieved: tuple[UUID, ...]


@dataclass(frozen=True)
class RetrievalReport:
    cases: tuple[CaseResult, ...]
    mean_recall: float
    mean_precision: float
    mrr: float

    @property
    def passed(self) -> bool:
        return bool(self.cases)


# A search returns the ranked document ids for a (query, domain, top_k).
SearchFn = Callable[[str, str, int], Awaitable[Sequence[UUID]]]


def _metrics(retrieved: Sequence[UUID], relevant: frozenset[UUID]) -> tuple[float, float, float]:
    if not relevant:
        return (0.0, 0.0, 0.0)
    retrieved_set = set(retrieved)
    hits = retrieved_set & relevant
    recall = len(hits) / len(relevant)
    precision = (len(hits) / len(retrieved)) if retrieved else 0.0
    rr = 0.0
    for rank, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            rr = 1.0 / rank
            break
    return (recall, precision, rr)


async def evaluate_retrieval(
    search: SearchFn, cases: Sequence[RetrievalCase], *, top_k: int = 5
) -> RetrievalReport:
    """Run each golden case through ``search`` and aggregate recall/precision/MRR."""
    results: list[CaseResult] = []
    for case in cases:
        retrieved = tuple(await search(case.query, case.domain, top_k))
        recall, precision, rr = _metrics(retrieved, case.relevant_document_ids)
        results.append(
            CaseResult(
                query=case.query,
                recall=recall,
                precision=precision,
                reciprocal_rank=rr,
                retrieved=retrieved,
            )
        )
    n = len(results) or 1
    return RetrievalReport(
        cases=tuple(results),
        mean_recall=sum(r.recall for r in results) / n,
        mean_precision=sum(r.precision for r in results) / n,
        mrr=sum(r.reciprocal_rank for r in results) / n,
    )
