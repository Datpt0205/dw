"""Entitlement service: plan-level capability checks (implements ``EntitlementPort``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from dw_kernel.errors import EntitlementDeniedError
from dw_platform.application.access_context import AccessContext
from dw_platform.domain.entities import Plan

# Canonical POC plans; the seeded DB rows mirror these (system of record for
# billing integrations later — the catalog here is the runtime source).
DEFAULT_PLANS: dict[str, Plan] = {
    "basic": Plan(
        plan_id="basic",
        name="Basic",
        features=frozenset({"work_ops_worker"}),
        quotas={"runs_per_day": 20},
    ),
    "professional": Plan(
        plan_id="professional",
        name="Professional",
        features=frozenset({"work_ops_worker", "tender_worker", "knowledge_search"}),
        quotas={"runs_per_day": 200},
    ),
    "enterprise": Plan(
        plan_id="enterprise",
        name="Enterprise",
        features=frozenset(
            {"work_ops_worker", "tender_worker", "knowledge_search", "audit_export"}
        ),
        quotas={"runs_per_day": 2000},
    ),
}


@dataclass(frozen=True)
class PlanEntitlementService:
    """Checks features against the plan catalog + per-tenant feature flags."""

    plans: Mapping[str, Plan]

    def has_feature(self, context: AccessContext, feature: str) -> bool:
        if context.has_feature(feature):  # per-tenant override, resolved at build
            return True
        plan = self.plans.get(context.plan_id)
        return plan is not None and feature in plan.features

    async def require_feature(self, context: AccessContext, feature: str) -> None:
        if self.has_feature(context, feature):
            return
        raise EntitlementDeniedError(
            "plan does not include this capability",
            details={"feature": feature, "plan_id": context.plan_id},
        )
