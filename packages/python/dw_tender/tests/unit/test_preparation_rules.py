"""DW01 deterministic rules + gates."""

from __future__ import annotations

import pytest

from dw_tender.application.preparation.rules import (
    Method,
    ProcurementRules,
    approach_gate,
    solicitation_gate,
)

pytestmark = pytest.mark.unit

RULES = ProcurementRules(
    version="1",
    currency="VND",
    # Ngưỡng theo Phụ lục G (01-QT/MH/HDCV/FPT v2/0).
    methods=(
        Method("direct_purchase", "Mua sắm trực tiếp", 10_000_000, 1),
        Method("rfq", "Chào giá cạnh tranh", 5_000_000_000, 3),
        Method("open_tender", "Đấu thầu", None, 3),
    ),
    weighted_total_must_equal=100,
    require_mandatory_criteria=True,
    legal_review_required_above=100_000_000,
    finance_review_required_above=5_000_000_000,
    tco_required_above=5_000_000_000,
    specialist_review_above=300_000_000,
    require_approved_pr=True,
    require_budget=True,
    require_deadline=True,
    require_owner=True,
)


def test_method_selection_by_value() -> None:
    # G1: <10tr trực tiếp; 10tr-5ty chào giá; >5tỷ đấu thầu.
    assert RULES.select_method(5_000_000).key == "direct_purchase"
    assert RULES.select_method(500_000_000).key == "rfq"
    assert RULES.select_method(5_000_000_000).key == "rfq"
    assert RULES.select_method(7_500_000_000).key == "open_tender"


def test_review_thresholds() -> None:
    # G3: pháp chế xem xét hợp đồng trên 100 triệu.
    assert not RULES.needs_legal_review(100_000_000)
    assert RULES.needs_legal_review(2_500_000_000)
    # G4: TCO bắt buộc cho gói trên 5 tỷ.
    assert not RULES.needs_tco(2_500_000_000)
    assert RULES.needs_tco(7_500_000_000)
    # G3: hàng chuyên môn trên 300 triệu → Trưởng BP cho ý kiến.
    assert not RULES.needs_specialist_review(300_000_000)
    assert RULES.needs_specialist_review(2_500_000_000)


def test_approach_gate_passes_when_complete() -> None:
    result = approach_gate(
        rules=RULES,
        has_approved_pr=True,
        estimated_value_minor=2_500_000_000,
        currency="VND",
        deadline="45 ngày",
        owner_name="An",
        method=RULES.select_method(2_500_000_000),
        supplier_count_planned=3,
        open_blocking_clarifications=0,
    )
    assert result.passed


def test_approach_gate_fails_without_pr_and_suppliers() -> None:
    result = approach_gate(
        rules=RULES,
        has_approved_pr=False,
        estimated_value_minor=0,
        currency="VND",
        deadline=None,
        owner_name="",
        method=RULES.select_method(2_500_000_000),
        supplier_count_planned=1,
        open_blocking_clarifications=2,
    )
    assert not result.passed
    assert len(result.reasons) >= 4


def test_solicitation_gate_requires_weights_sum_100() -> None:
    method = RULES.select_method(2_500_000_000)
    ok = solicitation_gate(
        rules=RULES,
        weighted_total=100,
        has_mandatory_criteria=True,
        shortlist_count=3,
        method=method,
        missing_sections=[],
    )
    assert ok.passed
    bad = solicitation_gate(
        rules=RULES,
        weighted_total=90,
        has_mandatory_criteria=True,
        shortlist_count=3,
        method=method,
        missing_sections=[],
    )
    assert not bad.passed
