"""Dispatch approval policy (blueprint §7.9, §11.3).

Pure domain logic: given an action and the requester context, decide whether a
human must approve before dispatch. POC autonomy is A2 — even auto-eligible
actions go through the human review gate; the policy still computes and records
the reasons so the approver sees WHY.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dw_work_ops.domain.entities import ActionItem
from dw_work_ops.domain.value_objects.confidence import Confidence, RiskLevel


@dataclass(frozen=True, slots=True)
class DispatchPolicyContext:
    requester_department: str
    min_assignee_confidence: Confidence = field(default_factory=lambda: Confidence(0.90))
    autonomy_level: str = "A2"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    requires_approval: bool
    reasons: tuple[str, ...] = ()

    @classmethod
    def allow(cls) -> PolicyDecision:
        return cls(requires_approval=False)

    @classmethod
    def require(cls, *reasons: str) -> PolicyDecision:
        return cls(requires_approval=True, reasons=tuple(reasons))


@dataclass(frozen=True)
class CanAutoDispatchAction:
    """Specification object evaluated per action item."""

    def evaluate(self, action: ActionItem, ctx: DispatchPolicyContext) -> PolicyDecision:
        reasons: list[str] = []
        if action.risk_level is not RiskLevel.LOW:
            reasons.append("risk_not_low")
        if action.assignee is None:
            reasons.append("assignee_unresolved")
        else:
            if action.assignee.department != ctx.requester_department:
                reasons.append("cross_department")
            if not action.assignee.confidence.meets(ctx.min_assignee_confidence):
                reasons.append("low_assignee_confidence")
        if action.due_date_inferred:
            reasons.append("due_date_inferred")
        if ctx.autonomy_level in ("A0", "A1", "A2"):
            reasons.append("autonomy_a2_requires_review")
        if reasons:
            return PolicyDecision.require(*reasons)
        return PolicyDecision.allow()


@dataclass(frozen=True, slots=True)
class GateResult:
    """Aggregated policy outcome for a batch of actions."""

    decisions: dict[str, PolicyDecision] = field(default_factory=dict)

    @property
    def any_requires_approval(self) -> bool:
        return any(d.requires_approval for d in self.decisions.values())
