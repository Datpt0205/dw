"""Legal constraints extracted from retrieved regulation passages (RAG).

"LLM drafts; deterministic code decides": the model only COPIES a number and
the sentence containing it out of the retrieved passages; this module verifies
that copy against the passages (anti-hallucination) and the workflow applies
the verified number deterministically. Nothing here invents a threshold.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LegalConstraintExtraction(BaseModel):
    """Model output: a quantitative constraint copied from the passages."""

    model_config = ConfigDict(extra="forbid")

    min_bid_preparation_days: int | None = Field(
        default=None,
        ge=1,
        le=365,
        description=(
            "Số ngày tối thiểu chuẩn bị hồ sơ dự thầu, chỉ khi con số xuất hiện "
            "NGUYÊN VĂN trong trích đoạn và áp dụng cho hình thức được nêu"
        ),
    )
    article_ref: str = Field(
        default="", description="Số điều/khoản nêu trong trích đoạn (vd 'Điều 45 khoản 1')"
    )
    source_quote: str = Field(
        default="", description="Câu chứa con số, chép nguyên văn từ trích đoạn"
    )


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def verified_constraint(
    extraction: LegalConstraintExtraction, passages: list[str]
) -> dict[str, Any] | None:
    """Accept the extraction only if it is literally supported by a passage.

    The quote must appear verbatim inside one of the retrieved passages and
    must itself contain the extracted number — a hallucinated constraint fails
    both checks and is discarded (the deterministic default window applies).
    """
    days = extraction.min_bid_preparation_days
    quote = _norm(extraction.source_quote)
    if days is None or len(quote) < 15:
        return None
    if not any(quote in _norm(passage) for passage in passages):
        return None
    # The number must be in the quoted sentence itself ("05" counts as 5).
    if not re.search(rf"(?<!\d)0?{days}(?!\d)", quote):
        return None
    return {
        "min_bid_preparation_days": days,
        "article_ref": extraction.article_ref.strip(),
        "source_quote": extraction.source_quote.strip(),
    }
