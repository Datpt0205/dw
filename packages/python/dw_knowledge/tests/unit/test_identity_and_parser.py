"""Deterministic ids (idempotent upsert) + plaintext/markdown parser."""

from __future__ import annotations

import uuid

import pytest

from dw_knowledge.adapters.text_parser import PlaintextParser
from dw_knowledge.identity import chunk_id_for, document_id_for

pytestmark = pytest.mark.unit

T1 = uuid.uuid4()
W1 = uuid.uuid4()


def test_document_id_is_stable_for_same_logical_document() -> None:
    a = document_id_for(
        tenant_id=T1, workspace_id=W1, domain="policy", title="Quy chế", source_version="1"
    )
    b = document_id_for(
        tenant_id=T1, workspace_id=W1, domain="policy", title="Quy chế", source_version="1"
    )
    assert a == b  # idempotent re-ingest overwrites, not duplicates
    c = document_id_for(
        tenant_id=T1, workspace_id=W1, domain="policy", title="Quy chế", source_version="2"
    )
    assert a != c  # new version = new document id


def test_global_scope_id_is_tenant_independent() -> None:
    t2 = uuid.uuid4()
    a = document_id_for(
        tenant_id=T1,
        workspace_id=W1,
        domain="legal",
        title="Luật 22/2023",
        source_version="1",
        scope="global",
    )
    b = document_id_for(
        tenant_id=t2,
        workspace_id=uuid.uuid4(),
        domain="legal",
        title="Luật 22/2023",
        source_version="1",
        scope="global",
    )
    assert a == b  # global legal doc is the same regardless of ingesting tenant


def test_chunk_id_is_stable_per_seq() -> None:
    doc = uuid.uuid4()
    a = chunk_id_for(document_id=doc, index_version="v1", seq=3)
    assert a == chunk_id_for(document_id=doc, index_version="v1", seq=3)
    assert a != chunk_id_for(document_id=doc, index_version="v1", seq=4)
    assert a != chunk_id_for(document_id=doc, index_version="v2", seq=3)


async def test_plaintext_parser_extracts_title_and_text() -> None:
    parser = PlaintextParser()
    assert parser.supports("text/markdown", "quy-che.md")
    assert not parser.supports("application/pdf", "luat.pdf")  # Phase B (Docling)
    parsed = await parser.parse(b"# Quy che mua sam\nNoi dung...", "text/markdown", "x.md")
    assert parsed.detected_title == "Quy che mua sam"
    assert "Noi dung" in parsed.text
