import uuid

import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
PRINCIPAL = uuid.uuid4()


class FakeMembershipLookup:
    async def find_access(
        self, subject: str, issuer: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        if subject == "dev|an.nguyen" and tenant_id == TENANT and workspace_id == WORKSPACE:
            return MembershipAccess(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                principal_id=PRINCIPAL,
                roles=frozenset({"member"}),
                scopes=frozenset({"work_ops.read"}),
                groups=frozenset(),
                clearance="internal",
                plan_id="professional",
                feature_flags=frozenset(),
            )
        return None


def make_container() -> ApiContainer:
    async def ok_probe() -> CheckState:
        return "ok"

    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok_probe}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=DbAccessContextFactory(FakeMembershipLookup()),
        identity_bootstrap=None,
        uow_factory=None,
        authorization=ScopeAuthorizationService(),
        entitlement=PlanEntitlementService(DEFAULT_PLANS),
    )


async def call_me(headers: dict[str, str]) -> httpx.Response:
    app = create_app(make_container())
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/me", headers=headers)


def auth_headers(tenant: uuid.UUID = TENANT, workspace: uuid.UUID = WORKSPACE) -> dict[str, str]:
    token = DevTokenVerifier(SECRET).issue("dev|an.nguyen", email="an@alpha.local")
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(tenant),
        "X-Workspace-Id": str(workspace),
    }


async def test_me_returns_access_context() -> None:
    response = await call_me(auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == str(TENANT)
    assert body["principal_id"] == str(PRINCIPAL)
    assert body["roles"] == ["member"]
    assert body["plan_id"] == "professional"


async def test_me_without_token_401() -> None:
    response = await call_me({"X-Tenant-Id": str(TENANT), "X-Workspace-Id": str(WORKSPACE)})
    assert response.status_code == 403 or response.status_code == 401
    assert response.json()["code"] in ("permission_denied", "tenant_context_missing")


async def test_me_with_garbage_token_403() -> None:
    headers = auth_headers()
    headers["Authorization"] = "Bearer not-a-real-token"
    response = await call_me(headers)
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_me_foreign_tenant_denied() -> None:
    response = await call_me(auth_headers(tenant=uuid.uuid4()))
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_me_missing_tenant_header_401() -> None:
    headers = auth_headers()
    del headers["X-Tenant-Id"]
    response = await call_me(headers)
    assert response.status_code == 401
    assert response.json()["code"] == "tenant_context_missing"
