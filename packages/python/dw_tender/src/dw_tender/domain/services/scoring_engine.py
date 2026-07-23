"""Deterministic weighted scoring + compliance gate (blueprint §12.2).

The LLM proposes raw scores and evidence; THIS code decides. Same inputs →
same outputs, always. Mandatory criteria are never satisfied without located
evidence (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from dw_tender.domain.entities import ComplianceFinding, FindingStatus, Requirement
from dw_tender.domain.exceptions import InvalidScoringConfigError
from dw_tender.domain.value_objects.scoring import RequirementKind


@dataclass(frozen=True, slots=True)
class ScoringPolicy:
    """Versioned deterministic policy loaded from configs/policies."""

    policy_version: str
    require_evidence_for_mandatory: bool = True
    disqualify_on_mandatory_fail: bool = True
    min_total_score: Decimal = Decimal("60")
    score_decimal_places: int = 2


@dataclass(frozen=True, slots=True)
class SupplierScore:
    supplier_name: str
    total_score: Decimal
    mandatory_passed: bool
    eligible: bool
    violations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "supplier_name": self.supplier_name,
            "total_score": str(self.total_score),
            "mandatory_passed": self.mandatory_passed,
            "eligible": self.eligible,
            "violations": list(self.violations),
        }


@dataclass(frozen=True, slots=True)
class GateOutcome:
    scores: tuple[SupplierScore, ...]
    top_supplier: str | None
    gate_passed: bool
    violations: tuple[str, ...]


class ScoringEngine:
    """Pure domain service — no IO, no model, no clock."""

    def __init__(self, policy: ScoringPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> ScoringPolicy:
        return self._policy

    def validate_requirements(self, requirements: list[Requirement]) -> None:
        weighted = [r for r in requirements if r.kind is RequirementKind.WEIGHTED]
        if not weighted:
            raise InvalidScoringConfigError("at least one weighted requirement is required")
        total = sum((r.weight for r in weighted), Decimal(0))
        if total != Decimal(1):
            raise InvalidScoringConfigError(
                f"weighted requirement weights must sum to 1, got {total}"
            )

    def score_supplier(
        self,
        supplier_name: str,
        requirements: list[Requirement],
        findings: list[ComplianceFinding],
    ) -> SupplierScore:
        by_code = {f.requirement_code: f for f in findings if f.supplier_name == supplier_name}
        violations: list[str] = []
        mandatory_passed = True

        for requirement in requirements:
            finding = by_code.get(requirement.code)
            if requirement.kind is RequirementKind.MANDATORY:
                if finding is None:
                    mandatory_passed = False
                    violations.append(f"{requirement.code}:no_finding")
                    continue
                if finding.status is not FindingStatus.COMPLIANT:
                    mandatory_passed = False
                    violations.append(f"{requirement.code}:{finding.status.value}")
                elif self._policy.require_evidence_for_mandatory and not finding.evidence:
                    # Never conclude a mandatory criterion is met without evidence.
                    mandatory_passed = False
                    violations.append(f"{requirement.code}:missing_evidence")

        total = Decimal(0)
        for requirement in requirements:
            if requirement.kind is not RequirementKind.WEIGHTED:
                continue
            finding = by_code.get(requirement.code)
            raw = finding.raw_score if finding is not None else Decimal(0)
            total += raw * requirement.weight

        quantum = Decimal(10) ** -self._policy.score_decimal_places
        total = total.quantize(quantum, rounding=ROUND_HALF_UP)

        eligible = total >= self._policy.min_total_score
        if self._policy.disqualify_on_mandatory_fail and not mandatory_passed:
            eligible = False
        if total < self._policy.min_total_score:
            violations.append(f"total_below_min:{total}")

        return SupplierScore(
            supplier_name=supplier_name,
            total_score=total,
            mandatory_passed=mandatory_passed,
            eligible=eligible,
            violations=tuple(violations),
        )

    def evaluate(
        self,
        requirements: list[Requirement],
        findings: list[ComplianceFinding],
        recommended_supplier: str | None,
    ) -> GateOutcome:
        """Score every supplier and check the drafted recommendation."""
        self.validate_requirements(requirements)
        suppliers = sorted({f.supplier_name for f in findings})
        scores = tuple(self.score_supplier(name, requirements, findings) for name in suppliers)

        eligible = [s for s in scores if s.eligible]
        # Deterministic tie-break: score desc, then name asc.
        eligible.sort(key=lambda s: (-s.total_score, s.supplier_name))
        top = eligible[0].supplier_name if eligible else None

        violations: list[str] = []
        if top is None:
            violations.append("no_eligible_supplier")
        elif recommended_supplier != top:
            violations.append(f"recommendation_mismatch:draft={recommended_supplier},gate={top}")

        return GateOutcome(
            scores=scores,
            top_supplier=top,
            gate_passed=not violations,
            violations=tuple(violations),
        )
