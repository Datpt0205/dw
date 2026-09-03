"""CompositeParser routing + PlaintextParser behaviour (B2)."""

from __future__ import annotations

import pytest

from dw_knowledge.adapters.composite_parser import CompositeParser
from dw_knowledge.adapters.docling_parser import DoclingDocumentParser
from dw_knowledge.adapters.text_parser import PlaintextParser

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_plaintext_parser_supports_and_parses() -> None:
    parser = PlaintextParser()
    assert parser.supports("text/plain", "a.txt")
    assert parser.supports("", "notes.md")
    assert not parser.supports("application/pdf", "scan.pdf")

    parsed = await parser.parse(b"# Tieu de\nNoi dung", "text/markdown", "doc.md")
    assert "Noi dung" in parsed.text
    assert parsed.detected_title == "Tieu de"


@pytest.mark.asyncio
async def test_composite_routes_text_to_plaintext() -> None:
    composite = CompositeParser(parsers=[PlaintextParser(), DoclingDocumentParser()])
    # A .txt is supported and handled by the (cheap) plaintext parser — no docling.
    assert composite.supports("text/plain", "a.txt")
    parsed = await composite.parse(b"hello world", "text/plain", "a.txt")
    assert parsed.text == "hello world"


@pytest.mark.asyncio
async def test_composite_reports_pdf_supported_via_docling() -> None:
    composite = CompositeParser(parsers=[PlaintextParser(), DoclingDocumentParser()])
    # Docling advertises PDF support without needing the heavy import (supports()
    # is metadata-only); actual parse() would lazily import docling.
    assert composite.supports("application/pdf", "scan.pdf")


@pytest.mark.asyncio
async def test_composite_rejects_unsupported() -> None:
    composite = CompositeParser(parsers=[PlaintextParser()])
    assert not composite.supports("application/zip", "a.zip")
    with pytest.raises(ValueError):
        await composite.parse(b"...", "application/zip", "a.zip")


def test_docling_supports_matrix() -> None:
    parser = DoclingDocumentParser()
    for name in ("a.pdf", "b.docx", "c.pptx", "d.xlsx", "e.png", "f.html"):
        assert parser.supports("", name), name
    assert not parser.supports("", "g.zip")
