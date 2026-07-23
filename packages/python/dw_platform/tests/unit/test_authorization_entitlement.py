import uuid

import pytest

from dw_kernel.errors import EntitlementDeniedError, PermissionDeniedError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService

pytestmark = pytest.mark.unit


def make_context(**overrides: object) -> AccessContext:
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "principal_id": uuid.uuid4(),
        "roles": frozenset({"member"}),
        "scopes": frozenset({"work_ops.read"}),
        "plan_id": "basic",
    }
    defaults.update(overrides)
    return AccessContext(**defaults)


async def test_scope_allows_action() -> None:
    service = ScopeAuthorizationService()
    await service.require(context=make_context(), action="work_ops.read", resource_type="meeting")


async def test_missing_scope_denied_with_details() -> None:
    service = ScopeAuthorizationService()
    with pytest.raises(PermissionDeniedError) as excinfo:
        await service.require(
            context=make_context(),
            action="work_ops.write",
            resource_type="meeting",
            resource_id="m-1",
        )
    assert excinfo.value.details["action"] == "work_ops.write"


async def test_platform_admin_bypasses_scopes() -> None:
    service = ScopeAuthorizationService()
    admin = make_context(roles=frozenset({"platform_admin"}), scopes=frozenset())
    await service.require(context=admin, action="anything.at_all", resource_type="any")


async def test_entitlement_by_plan_and_override() -> None:
    service = PlanEntitlementService(DEFAULT_PLANS)
    basic = make_context(plan_id="basic")
    await service.require_feature(basic, "work_ops_worker")
    with pytest.raises(EntitlementDeniedError):
        await service.require_feature(basic, "tender_worker")

    # per-tenant override wins even on basic plan
    with_override = make_context(plan_id="basic", feature_flags=frozenset({"tender_worker"}))
    await service.require_feature(with_override, "tender_worker")


async def test_entitlement_unknown_plan_fails_closed() -> None:
    service = PlanEntitlementService(DEFAULT_PLANS)
    with pytest.raises(EntitlementDeniedError):
        await service.require_feature(make_context(plan_id="ghost"), "work_ops_worker")
