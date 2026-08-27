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

# The one question asked about bid-preparation time, wherever it is asked from:
# the drafting node, the CP2 gate, and the background law watcher. Comparing two
# answers only means something if the question did not change between them, and
# it was three hand-copied strings across two packages before this.
#
# It also decides a cache key. Same string, same tenant, same day = one paid
# search instead of three.
LEGAL_WINDOW_QUERY = "thời gian chuẩn bị hồ sơ dự thầu tối thiểu kể từ ngày phát hành hồ sơ"


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


def numbered_passages(quotes: list[str]) -> str:
    """How retrieved passages are presented to the model.

    Numbering is not decoration: the prompt refers to passages by index, and the
    extraction is only accepted if its quote is found in one of these, so the
    text handed over must be exactly the text checked against.
    """
    return "\n".join(f"[{i}] {p}" for i, p in enumerate(quotes, start=1) if p)


class RequiredSectionsExtraction(BaseModel):
    """Model output: the sections a solicitation package must contain by law."""

    model_config = ConfigDict(extra="forbid")

    sections: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Tên các mục bắt buộc của HSMT, CHÉP NGUYÊN VĂN cụm từ xuất hiện "
            "trong trích đoạn. Không diễn giải, không gộp, không thêm mục nào "
            "trích đoạn không nêu."
        ),
    )
    article_ref: str = Field(default="", description="Số điều/khoản nêu danh mục này")
    source_quote: str = Field(
        default="", description="Câu nêu danh mục, chép nguyên văn từ trích đoạn"
    )


def verified_sections(
    extraction: RequiredSectionsExtraction, passages: list[str]
) -> dict[str, Any] | None:
    """Accept the list only if every name in it was actually on the page.

    Same shape of contract as ``verified_constraint``, with one deliberate
    difference. There, the number had to sit inside the quoted sentence, because
    a figure is a single claim made in one place. A statutory list of required
    sections routinely runs across several clauses, so demanding all of it inside
    one sentence would reject correct extractions. Instead the quote anchors
    WHICH provision this came from, and every section name must appear verbatim
    somewhere in the retrieved text.

    What that still forbids is the thing worth forbidding: a model naming a
    requirement the sources never mentioned.
    """
    quote = _norm(extraction.source_quote)
    names = [name.strip() for name in extraction.sections if name.strip()]
    if not names or len(quote) < 15:
        return None
    if not any(quote in _norm(passage) for passage in passages):
        return None
    corpus = " ".join(_norm(passage) for passage in passages)
    if any(_norm(name) not in corpus for name in names):
        return None
    return {
        "sections": names,
        "article_ref": extraction.article_ref.strip(),
        "source_quote": extraction.source_quote.strip(),
    }
