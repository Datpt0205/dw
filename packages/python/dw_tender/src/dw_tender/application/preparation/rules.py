"""Deterministic procurement rules + gates (DW01).

"LLM drafts; deterministic code decides." Method selection, approval tiers and
the CP1/CP2 gates are computed here from the versioned rule pack — never by the
model. Values come from ``configs/policies/dw01/procurement_rules_v1.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Method:
    key: str
    label: str
    max_value: int | None
    min_suppliers: int


@dataclass(frozen=True, slots=True)
class ApprovalTier:
    """Who may decide each checkpoint for packages up to ``max_value``."""

    max_value: int | None
    cp1_role: str
    cp2_role: str
    cp3_role: str = "approver"
    cp4_role: str = "approver"


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]

    @classmethod
    def of(cls, failures: list[str]) -> GateResult:
        return cls(passed=not failures, reasons=tuple(failures))


@dataclass(frozen=True)
class ProcurementRules:
    version: str
    currency: str
    methods: tuple[Method, ...]
    weighted_total_must_equal: int
    require_mandatory_criteria: bool
    legal_review_required_above: int
    finance_review_required_above: int
    require_approved_pr: bool
    require_budget: bool
    require_deadline: bool
    require_owner: bool
    # Phụ lục G4: gói TSCĐ/CNTT trên ngưỡng phải tính Tổng chi phí sở hữu.
    tco_required_above: int = 0
    # Phụ lục G3: hàng chuyên môn nhóm 1 trên ngưỡng → Trưởng BP mua sắm cho ý kiến.
    specialist_review_above: int = 0
    mandatory_criteria: tuple[tuple[str, str], ...] = ()
    weighted_criteria: tuple[tuple[str, str, int], ...] = ()
    payment_term_template: str = ""
    tax_term_template: str = ""
    response_structure: tuple[str, ...] = ()
    # Phụ lục: ma trận thẩm quyền theo giá trị gói (CP1 thẩm định, CP2 phê duyệt).
    approval_tiers: tuple[ApprovalTier, ...] = ()
    # Role dùng khi rule pack chưa khai tier nào (giữ hành vi cũ).
    default_approver_role: str = "approver"

    def approver_role_for(self, value_minor: int, checkpoint: str) -> str:
        """Membership role that must receive/decide this checkpoint.

        Deterministic and versioned: a 500 tỷ package sends CP2 to the head of
        procurement, a small one keeps both checkpoints with the specialist.
        The model has no say in this.
        """
        for tier in self.approval_tiers:
            if tier.max_value is None or value_minor <= tier.max_value:
                return {
                    "CP1": tier.cp1_role,
                    "CP2": tier.cp2_role,
                    "CP3": tier.cp3_role,
                    "CP4": tier.cp4_role,
                }.get(checkpoint.upper(), tier.cp1_role)
        return self.default_approver_role

    def select_method(self, value_minor: int) -> Method:
        """Cheapest/fastest method whose ceiling still covers the package value."""
        for method in self.methods:
            if method.max_value is None or value_minor <= method.max_value:
                return method
        return self.methods[-1]

    def needs_legal_review(self, value_minor: int) -> bool:
        return value_minor > self.legal_review_required_above

    def needs_finance_review(self, value_minor: int) -> bool:
        return value_minor > self.finance_review_required_above

    def needs_tco(self, value_minor: int) -> bool:
        return self.tco_required_above > 0 and value_minor > self.tco_required_above

    def needs_specialist_review(self, value_minor: int) -> bool:
        return self.specialist_review_above > 0 and value_minor > self.specialist_review_above


def approach_gate(
    *,
    rules: ProcurementRules,
    has_approved_pr: bool,
    estimated_value_minor: int,
    currency: str,
    deadline: str | None,
    owner_name: str,
    method: Method,
    supplier_count_planned: int,
    open_blocking_clarifications: int,
) -> GateResult:
    """CP1 gate: is the procurement approach complete and consistent?"""
    failures: list[str] = []
    if rules.require_approved_pr and not has_approved_pr:
        failures.append("Thiếu tham chiếu PR đã phê duyệt.")
    if rules.require_budget and estimated_value_minor <= 0:
        failures.append("Thiếu ngân sách/dự toán (estimated_value).")
    if not currency.strip():
        failures.append("Thiếu đơn vị tiền tệ.")
    if rules.require_deadline and not deadline:
        failures.append("Thiếu thời hạn (deadline).")
    if rules.require_owner and not owner_name.strip():
        failures.append("Thiếu người phụ trách (owner).")
    if supplier_count_planned < method.min_suppliers:
        failures.append(
            f"Phương án {method.label} cần tối thiểu {method.min_suppliers} nhà cung cấp "
            f"— đang có {supplier_count_planned}."
        )
    if open_blocking_clarifications > 0:
        failures.append(
            f"Còn {open_blocking_clarifications} câu hỏi làm rõ bắt buộc chưa được trả lời."
        )
    return GateResult.of(failures)


def solicitation_gate(
    *,
    rules: ProcurementRules,
    weighted_total: int,
    has_mandatory_criteria: bool,
    shortlist_count: int,
    method: Method,
    missing_sections: list[str],
    submission_window_days: int = 0,
    legal_min_window_days: int | None = None,
) -> GateResult:
    """CP2 gate: is the solicitation package complete, consistent, fair?

    ``legal_min_window_days`` is the RAG-extracted, code-verified minimum
    bid-preparation time — when present, a package whose submission window is
    shorter FAILS the gate (the law has teeth, not just a citation).
    """
    failures: list[str] = []
    for section in missing_sections:
        failures.append(f"Thiếu mục bắt buộc: {section}.")
    if (
        legal_min_window_days is not None
        and submission_window_days
        and submission_window_days < legal_min_window_days
    ):
        failures.append(
            f"Hạn nộp hồ sơ {submission_window_days} ngày ngắn hơn mức tối thiểu "
            f"{legal_min_window_days} ngày theo căn cứ pháp lý đã truy xuất."
        )
    if rules.require_mandatory_criteria and not has_mandatory_criteria:
        failures.append("Thiếu tiêu chí bắt buộc (pass/fail).")
    if weighted_total != rules.weighted_total_must_equal:
        failures.append(
            f"Tổng trọng số tiêu chí = {weighted_total}, phải bằng "
            f"{rules.weighted_total_must_equal}."
        )
    if shortlist_count < method.min_suppliers:
        failures.append(
            f"Shortlist có {shortlist_count} nhà cung cấp, cần tối thiểu {method.min_suppliers}."
        )
    return GateResult.of(failures)
