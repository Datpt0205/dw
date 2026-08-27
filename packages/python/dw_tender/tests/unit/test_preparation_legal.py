"""Anti-hallucination verification of RAG-extracted legal constraints.

The model may only COPY a number+sentence out of retrieved passages;
``verified_constraint`` must reject anything not literally supported, and the
CP2 gate must fail when the submission window undercuts a verified minimum.
"""

from __future__ import annotations

import pytest

from dw_tender.application.preparation.legal import (
    LegalConstraintExtraction,
    RequiredSectionsExtraction,
    verified_constraint,
    verified_sections,
)
from dw_tender.application.preparation.rules import (
    Method,
    ProcurementRules,
    effective_legal_minimum,
    solicitation_gate,
)

PASSAGE = (
    "Điều 45. Thời gian tổ chức lựa chọn nhà thầu. 1. Thời gian chuẩn bị hồ sơ "
    "dự thầu đối với đấu thầu rộng rãi trong nước tối thiểu là 18 ngày, kể từ "
    "ngày đầu tiên hồ sơ mời thầu được phát hành đến ngày có thời điểm đóng thầu."
)

pytestmark = pytest.mark.unit


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


# --- the law re-checked at signature time ------------------------------------


def test_law_that_grew_between_cp1_and_cp2_is_the_one_enforced() -> None:
    """The gap this closes: a package approved at CP1 sits for weeks, and the
    figure the CP2 gate enforces is whatever the law said when someone started
    typing. The background watcher reports a change every six hours; a package
    that moves CP1 → CP2 in an hour outruns it."""
    effective, note = effective_legal_minimum(drafted_days=18, live_days=25)

    assert effective == 25
    assert "khi soạn là 18 ngày" in note and "luật đã thay đổi" in note


def test_a_shorter_figure_today_does_not_relax_an_approved_deadline() -> None:
    """Tighten only.

    Relaxing a deadline someone already signed off, on the strength of a search
    result, is not a decision a gate makes by itself — and a shorter window is
    the direction that costs bidders their preparation time.
    """
    effective, note = effective_legal_minimum(drafted_days=25, live_days=18)

    assert effective == 25
    assert note == ""


def test_an_unreachable_source_is_not_a_change_in_the_law() -> None:
    """The single most dangerous confusion in this feature.

    ``None`` arrives from an exhausted provider chain, an unreachable page, and
    an answer that failed verification alike. Every one of them must leave the
    drafted figure in force: an outage may not be the reason a package cannot be
    signed, and it may not be reported as the law having moved either.
    """
    assert effective_legal_minimum(drafted_days=18, live_days=None) == (18, "")


def test_a_package_drafted_without_a_verified_figure_gains_one_if_today_has_it() -> None:
    """Drafting fell back to the deterministic default and cited nothing. If the
    sources are reachable now, the gate has a real figure to enforce for the
    first time — and no "the law changed" note, because nothing changed."""
    effective, note = effective_legal_minimum(drafted_days=None, live_days=25)

    assert effective == 25
    assert note == "", "chưa từng có số cũ thì không phải là luật đổi"


def test_no_figure_anywhere_leaves_the_gate_with_nothing_to_enforce() -> None:
    assert effective_legal_minimum(drafted_days=None, live_days=None) == (None, "")


def test_the_failure_message_says_the_law_moved_rather_than_blaming_the_typist() -> None:
    """A package can fail CP2 on the same numbers that passed CP1. Whoever reads
    that failure will assume someone typed a deadline wrong unless told."""
    effective, note = effective_legal_minimum(drafted_days=18, live_days=25)
    result = solicitation_gate(
        rules=_rules(),
        weighted_total=100,
        has_mandatory_criteria=True,
        shortlist_count=3,
        method=_rules().methods[0],
        missing_sections=[],
        submission_window_days=22,
        legal_min_window_days=effective,
        legal_min_note=note,
    )

    assert not result.passed
    reason = next(r for r in result.reasons if "25 ngày" in r)
    assert "22 ngày" in reason and "khi soạn là 18 ngày" in reason


# --- what the law says a package must contain --------------------------------


SECTIONS_PASSAGE = (
    "Điều 44. Nội dung hồ sơ mời thầu. 1. Hồ sơ mời thầu bao gồm: chỉ dẫn nhà "
    "thầu, bảng dữ liệu đấu thầu, tiêu chuẩn đánh giá, biểu mẫu dự thầu, phạm vi "
    "cung cấp, điều kiện hợp đồng và biểu mẫu hợp đồng."
)


def test_a_section_list_copied_off_the_page_is_accepted() -> None:
    extraction = RequiredSectionsExtraction(
        sections=["chỉ dẫn nhà thầu", "tiêu chuẩn đánh giá", "phạm vi cung cấp"],
        article_ref="Điều 44 khoản 1",
        source_quote="Hồ sơ mời thầu bao gồm: chỉ dẫn nhà thầu, bảng dữ liệu đấu thầu, "
        "tiêu chuẩn đánh giá",
    )

    verified = verified_sections(extraction, [SECTIONS_PASSAGE])

    assert verified is not None
    assert verified["sections"] == ["chỉ dẫn nhà thầu", "tiêu chuẩn đánh giá", "phạm vi cung cấp"]
    assert verified["article_ref"] == "Điều 44 khoản 1"


def test_a_requirement_the_page_never_mentioned_sinks_the_whole_list() -> None:
    """The failure this contract exists for.

    A model that knows procurement law will happily add a section it is sure
    about. On an approval card that reads as "the statute requires this", and
    nobody can tell the invented entry from the copied ones — so the list is
    rejected whole rather than silently trimmed.
    """
    extraction = RequiredSectionsExtraction(
        sections=["chỉ dẫn nhà thầu", "bảo lãnh thực hiện hợp đồng"],
        article_ref="Điều 44",
        source_quote="Hồ sơ mời thầu bao gồm: chỉ dẫn nhà thầu, bảng dữ liệu đấu thầu",
    )

    assert verified_sections(extraction, [SECTIONS_PASSAGE]) is None


def test_a_quote_that_is_not_on_the_page_is_rejected_even_if_the_names_are_real() -> None:
    """The quote is what says WHICH provision this came from. Without it the
    article reference on the card is unanchored."""
    extraction = RequiredSectionsExtraction(
        sections=["chỉ dẫn nhà thầu"],
        article_ref="Điều 44",
        source_quote="Theo quy định hiện hành, hồ sơ mời thầu phải có chỉ dẫn nhà thầu.",
    )

    assert verified_sections(extraction, [SECTIONS_PASSAGE]) is None


def test_an_empty_list_is_a_normal_answer_not_a_verified_one() -> None:
    """Most retrieved pages will not carry Điều 44. Returning nothing must not
    look the same as returning a verified empty requirement set."""
    extraction = RequiredSectionsExtraction(sections=[], article_ref="", source_quote="")

    assert verified_sections(extraction, [SECTIONS_PASSAGE]) is None


def test_a_list_spanning_two_clauses_is_still_accepted() -> None:
    """Deliberately looser than the day-count check, and the reason is in the
    text: a figure is one claim in one sentence, while a statutory list routinely
    runs across clauses. Demanding all of it inside the quoted sentence would
    reject correct extractions."""
    extraction = RequiredSectionsExtraction(
        sections=["chỉ dẫn nhà thầu", "biểu mẫu hợp đồng"],
        article_ref="Điều 44",
        source_quote="Hồ sơ mời thầu bao gồm: chỉ dẫn nhà thầu, bảng dữ liệu đấu thầu",
    )

    verified = verified_sections(extraction, [SECTIONS_PASSAGE])

    assert verified is not None, "'biểu mẫu hợp đồng' ở câu sau nhưng vẫn có trên trang"


def test_the_same_clause_verifies_at_two_different_granularities() -> None:
    """Why this output is displayed and not enforced, in one test.

    Measured 2026-08-26 over 8 live runs: the same clause of Điều 44 came back
    once as a single item carrying the whole semicolon list and once as its
    parts, and BOTH are honest copies that pass verification. Only one section
    name repeated across all seven accepted runs.

    That is fine for a card a person reads, and fatal for a gate: matching this
    against internal section keys would report the coarse form as one missing
    section and the fine form as five present ones, off the same statute and the
    same page. Enforcement needs a stable identity for a section first — a
    normalisation problem, not a retrieval one.
    """
    coarse = RequiredSectionsExtraction(
        sections=["chỉ dẫn nhà thầu, bảng dữ liệu đấu thầu, tiêu chuẩn đánh giá"],
        article_ref="Điều 44 khoản 1",
        source_quote="Hồ sơ mời thầu bao gồm: chỉ dẫn nhà thầu",
    )
    fine = RequiredSectionsExtraction(
        sections=["chỉ dẫn nhà thầu", "bảng dữ liệu đấu thầu", "tiêu chuẩn đánh giá"],
        article_ref="Điều 44 khoản 1",
        source_quote="Hồ sơ mời thầu bao gồm: chỉ dẫn nhà thầu",
    )

    assert verified_sections(coarse, [SECTIONS_PASSAGE]) is not None
    assert verified_sections(fine, [SECTIONS_PASSAGE]) is not None


def test_a_page_about_a_different_selection_regime_verifies_just_as_happily() -> None:
    """The other half of the measurement, and the more dangerous half.

    Asking "hồ sơ mời thầu phải có các nội dung" retrieved the article on
    selecting INVESTORS rather than contractors — a different chapter with a
    different list. Verification cannot catch this: every name really is on the
    page that was really retrieved. A gate fed that list would block contractor
    packages for missing sections that were never theirs.
    """
    investor_passage = (
        "Hồ sơ mời thầu bao gồm: phương án đầu tư kinh doanh; hiệu quả sử dụng "
        "đất hoặc hiệu quả đầu tư phát triển ngành, lĩnh vực, địa phương."
    )
    extraction = RequiredSectionsExtraction(
        sections=["phương án đầu tư kinh doanh"],
        article_ref="",
        source_quote="Hồ sơ mời thầu bao gồm: phương án đầu tư kinh doanh",
    )

    assert verified_sections(extraction, [investor_passage]) is not None, (
        "hợp đồng chép-rồi-kiểm không phân biệt được nhầm điều luật — đó là "
        "lý do danh mục này chỉ được HIỂN THỊ, không được dùng để chặn"
    )
