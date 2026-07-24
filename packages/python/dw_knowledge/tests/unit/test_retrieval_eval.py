"""Retrieval eval harness metrics (B6)."""

from __future__ import annotations

import uuid

import pytest

from dw_knowledge.retrieval_eval import RetrievalCase, evaluate_retrieval

D1 = uuid.uuid4()
D2 = uuid.uuid4()
D3 = uuid.uuid4()


@pytest.mark.asyncio
async def test_perfect_retrieval_scores_one() -> None:
    cases = [RetrievalCase(query="q", domain="legal", relevant_document_ids=frozenset({D1}))]

    async def search(query: str, domain: str, top_k: int):
        return [D1, D2]

    report = await evaluate_retrieval(search, cases, top_k=2)
    assert report.mean_recall == 1.0
    assert report.mean_precision == 0.5  # 1 of 2 retrieved is relevant
    assert report.mrr == 1.0  # relevant doc at rank 1
    assert report.passed


@pytest.mark.asyncio
async def test_reciprocal_rank_reflects_position() -> None:
    cases = [RetrievalCase(query="q", domain="legal", relevant_document_ids=frozenset({D3}))]

    async def search(query: str, domain: str, top_k: int):
        return [D1, D2, D3]  # relevant at rank 3

    report = await evaluate_retrieval(search, cases, top_k=3)
    assert report.mean_recall == 1.0
    assert report.mrr == pytest.approx(1 / 3)


@pytest.mark.asyncio
async def test_miss_scores_zero() -> None:
    cases = [RetrievalCase(query="q", domain="legal", relevant_document_ids=frozenset({D1}))]

    async def search(query: str, domain: str, top_k: int):
        return [D2, D3]

    report = await evaluate_retrieval(search, cases, top_k=2)
    assert report.mean_recall == 0.0
    assert report.mean_precision == 0.0
    assert report.mrr == 0.0


@pytest.mark.asyncio
async def test_aggregates_across_cases() -> None:
    cases = [
        RetrievalCase(query="a", domain="legal", relevant_document_ids=frozenset({D1})),
        RetrievalCase(query="b", domain="legal", relevant_document_ids=frozenset({D2})),
    ]

    async def search(query: str, domain: str, top_k: int):
        return [D1] if query == "a" else [D3]  # first hits, second misses

    report = await evaluate_retrieval(search, cases, top_k=1)
    assert report.mean_recall == 0.5
    assert len(report.cases) == 2
