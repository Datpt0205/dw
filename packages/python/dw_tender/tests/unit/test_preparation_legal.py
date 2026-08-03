"""Anti-hallucination verification of RAG-extracted legal constraints.

The model may only COPY a number+sentence out of retrieved passages;
``verified_constraint`` must reject anything not literally supported, and the
CP2 gate must fail when the submission window undercuts a verified minimum.
"""

from __future__ import annotations

from dw_tender.application.preparation.legal import (
    LegalConstraintExtraction,
    verified_constraint,
)
from dw_tender.application.preparation.rules import Method, ProcurementRules, solicitation_gate

PASSAGE = (
    "Điều 45. Thời gian tổ chức lựa chọn nhà thầu. 1. Thời gian chuẩn bị hồ sơ "
    "dự thầu đối với đấu thầu rộng rãi trong nước tối thiểu là 18 ngày, kể từ "
    "ngày đầu tiên hồ sơ mời thầu được phát hành đến ngày có thời điểm đóng thầu."
)


def test_verified_when_quote_and_number_match_passage() -> None:
    extraction = LegalConstraintExtraction(
        min_bid_preparation_days=18,
        article_ref="Điều 45 khoản 1",
        source_quote=(
            "Thời gian chuẩn bị hồ sơ dự thầu đối với đấu thầu rộng rãi trong "
            "nước tối thiểu là 18 ngày"
        ),
    )
    verified = verified_constraint(extraction, [PASSAGE])
    assert verified is not None
    assert verified["min_bid_preparation_days"] == 18
    assert verified["article_ref"] == "Điều 45 khoản 1"


def test_rejects_quote_not_present_in_passages() -> None:
    extraction = LegalConstraintExtraction(
        min_bid_preparation_days=18,
        source_quote="Thời gian chuẩn bị hồ sơ dự thầu tối thiểu là 18 ngày theo thông lệ.",
    )
    assert verified_constraint(extraction, [PASSAGE]) is None


def test_rejects_number_absent_from_quote() -> None:
    # Model claims 25 days but quotes a sentence that says 18 — hallucinated.
    extraction = LegalConstraintExtraction(
        min_bid_preparation_days=25,
        source_quote=(
            "Thời gian chuẩn bị hồ sơ dự thầu đối với đấu thầu rộng rãi trong "
            "nước tối thiểu là 18 ngày"
        ),
    )
    assert verified_constraint(extraction, [PASSAGE]) is None


def test_rejects_when_nothing_extracted() -> None:
    assert verified_constraint(LegalConstraintExtraction(), [PASSAGE]) is None


def test_accepts_leading_zero_day_numbers() -> None:
    passage = (
        "Đối với chào hàng cạnh tranh, thời gian chuẩn bị hồ sơ dự thầu tối "
        "thiểu là 05 ngày làm việc, kể từ ngày đầu tiên hồ sơ yêu cầu được phát hành."
    )
    extraction = LegalConstraintExtraction(
        min_bid_preparation_days=5,
        source_quote=("thời gian chuẩn bị hồ sơ dự thầu tối thiểu là 05 ngày làm việc"),
    )
    verified = verified_constraint(extraction, [passage])
    assert verified is not None and verified["min_bid_preparation_days"] == 5


def _rules() -> ProcurementRules:
    return ProcurementRules(
        version="test",
        currency="VND",
        methods=(Method(key="open_tender", label="Đấu thầu", max_value=None, min_suppliers=3),),
        weighted_total_must_equal=100,
        require_mandatory_criteria=True,
        legal_review_required_above=100_000_000,
        finance_review_required_above=5_000_000_000,
        require_approved_pr=True,
        require_budget=True,
        require_deadline=True,
        require_owner=True,
    )


def test_cp2_gate_fails_when_window_below_legal_minimum() -> None:
    result = solicitation_gate(
        rules=_rules(),
        weighted_total=100,
        has_mandatory_criteria=True,
        shortlist_count=3,
        method=_rules().methods[0],
        missing_sections=[],
        submission_window_days=10,
        legal_min_window_days=18,
    )
    assert not result.passed
    assert any("18 ngày" in reason for reason in result.reasons)


def test_cp2_gate_passes_when_window_meets_legal_minimum() -> None:
    result = solicitation_gate(
        rules=_rules(),
        weighted_total=100,
        has_mandatory_criteria=True,
        shortlist_count=3,
        method=_rules().methods[0],
        missing_sections=[],
        submission_window_days=22,
        legal_min_window_days=18,
    )
    assert result.passed
