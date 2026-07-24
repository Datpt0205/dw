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
            f"Phương án «{method.label}» cần tối thiểu {method.min_suppliers} nhà cung cấp "
            f"(đang có {supplier_count_planned})."
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
) -> GateResult:
    """CP2 gate: is the solicitation package complete, consistent, fair?"""
    failures: list[str] = []
    for section in missing_sections:
        failures.append(f"Thiếu mục bắt buộc: {section}.")
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
