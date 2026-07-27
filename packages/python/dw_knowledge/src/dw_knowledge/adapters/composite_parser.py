"""Composite parser: dispatch to the first adapter that supports the input.

Wired in the worker composition root as ``CompositeParser([PlaintextParser(),
DoclingDocumentParser()])`` — cheap plaintext/markdown handled directly, every
richer format (PDF/DOCX/XLSX/scans) falling through to Docling+OCR.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dw_knowledge.ports import DocumentParserPort, ParsedDocument


@dataclass
class CompositeParser:
    """Implements ``DocumentParserPort`` by delegating to the first match."""

    parsers: Sequence[DocumentParserPort]

    def supports(self, content_type: str, filename: str) -> bool:
        return any(p.supports(content_type, filename) for p in self.parsers)

    async def parse(self, data: bytes, content_type: str, filename: str) -> ParsedDocument:
        for parser in self.parsers:
            if parser.supports(content_type, filename):
                return await parser.parse(data, content_type, filename)
        raise ValueError(f"no parser supports content_type={content_type!r} filename={filename!r}")
