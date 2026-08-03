"""P5 Review Agent: schema validation + card rendering."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dw_tender.application.preparation.review import (
    ReviewCheck,
    ReviewRecommendation,
    review_card_lines,
)

pytestmark = pytest.mark.unit


def test_review_card_lines_render_verdict_checks_and_risks() -> None:
    review = ReviewRecommendation(
        recommendation="approve",
        rationale_summary="Phương án nhất quán với quy định.",
        key_checks=[
            ReviewCheck(check="Giá trị ↔ hình thức", result="pass"),
            ReviewCheck(check="Số NCC tối thiểu", result="pass"),
            ReviewCheck(check="Thời hạn", result="warn", note="45 ngày là sát"),
        ],
        risks=["Thị trường biến động giá"],
        confidence=0.9,
    )
    lines = review_card_lines(review)
    assert lines[0].startswith("🤖 Review Agent: ĐỀ XUẤT DUYỆT")
    assert "90%" in lines[0]
    assert any("2/3 hạng mục đạt" in line for line in lines)
    assert any("⚠️ Thời hạn" in line for line in lines)
    assert any("Rủi ro:" in line for line in lines)


def test_schema_rejects_invalid_verdict_and_confidence() -> None:
    with pytest.raises(ValidationError):
        ReviewRecommendation(
            recommendation="auto_approve",  # not in enum
            rationale_summary="x",
            confidence=0.5,
        )
    with pytest.raises(ValidationError):
        ReviewRecommendation(recommendation="approve", rationale_summary="x", confidence=1.5)
