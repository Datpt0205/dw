"""Docling multi-format parser + OCR (Phase B2), behind ``DocumentParserPort``.

Converts PDF / DOCX / PPTX / XLSX / HTML / CSV / images (scanned, via OCR) into
clean, table-aware Markdown that ``structure_aware_chunks`` can then split.

``docling`` (and its heavy ML stack: torch, layout + OCR models) is an OPTIONAL
dependency, installed only in the worker image where ingestion runs — never in
the API image. Import is lazy so ``dw_knowledge`` stays importable without it;
``supports()`` never needs docling, only ``parse()`` does.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from dw_knowledge.ports import ParsedDocument

# Extensions Docling can convert. Plaintext/Markdown are handled by the lighter
# PlaintextParser first (see CompositeParser) — kept here so Docling is a valid
# standalone fallback too.
_DOCLING_SUFFIXES = (
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".csv",
    ".md",
    ".markdown",
    ".adoc",
    ".asciidoc",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
)
_DOCLING_CONTENT_TYPES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/html",
    "text/csv",
    "image/png",
    "image/jpeg",
    "image/tiff",
    "image/bmp",
    "image/webp",
)
# OCR is meaningful only for these; toggling it off for born-digital office files
# keeps ingestion fast (no image model warm-up).
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


@dataclass
class DoclingDocumentParser:
    """Implements ``DocumentParserPort`` using Docling with OCR for scans.

    The converter is heavy to build (model warm-up), so it is created lazily and
    cached for the process lifetime.
    """

    do_ocr: bool = True
    _converter: Any = field(default=None, init=False, repr=False)

    def supports(self, content_type: str, filename: str) -> bool:
        ct = (content_type or "").split(";", 1)[0].strip().lower()
        name = (filename or "").lower()
        return ct in _DOCLING_CONTENT_TYPES or name.endswith(_DOCLING_SUFFIXES)

    def _build_converter(self) -> Any:
        # Imported lazily: docling pulls in torch + OCR models and is installed
        # only in the worker image.
        from docling.datamodel.base_models import InputFormat  # type: ignore[import-not-found]
        from docling.datamodel.pipeline_options import (  # type: ignore[import-not-found]
            PdfPipelineOptions,
        )
        from docling.document_converter import (  # type: ignore[import-not-found]
            DocumentConverter,
            PdfFormatOption,
        )

        pdf_options = PdfPipelineOptions()
        pdf_options.do_ocr = self.do_ocr
        pdf_options.do_table_structure = True
        pdf_options.table_structure_options.do_cell_matching = True
        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
                InputFormat.IMAGE: PdfFormatOption(pipeline_options=pdf_options),
            }
        )

    def _converter_ready(self) -> Any:
        if self._converter is None:
            self._converter = self._build_converter()
        return self._converter

    def _convert_sync(self, data: bytes, filename: str) -> ParsedDocument:
        from docling.datamodel.base_models import DocumentStream

        converter = self._converter_ready()
        source = DocumentStream(name=filename or "document", stream=BytesIO(data))
        result = converter.convert(source)
        doc = result.document
        # Markdown preserves headings + tables → best input for structure-aware chunking.
        text = doc.export_to_markdown()
        page_count = len(getattr(doc, "pages", []) or []) or None
        title = getattr(doc, "name", None) or None
        warnings: list[str] = []
        if not text.strip():
            warnings.append("empty_extraction")
        return ParsedDocument(
            text=text,
            detected_title=(title[:200] if title else None),
            page_count=page_count,
            warnings=tuple(warnings),
        )

    async def parse(self, data: bytes, content_type: str, filename: str) -> ParsedDocument:
        # Docling conversion (and OCR) is CPU/GPU-bound and blocking — run it off
        # the event loop so the worker's heartbeat/other consumers keep ticking.
        return await asyncio.to_thread(self._convert_sync, data, filename)
