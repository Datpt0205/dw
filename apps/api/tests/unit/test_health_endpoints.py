import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_api.bootstrap import ApiContainer, build_container
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService

pytestmark = pytest.mark.unit


def make_container(db_state: CheckState) -> ApiContainer:
    async def fake_db_probe() -> CheckState:
        return db_state

    return ApiContainer(
        settings=ApiSettings(profile="test"),
        engine=None,
        health_service=HealthService(probes={"database": fake_db_probe}),
        token_verifier=None,
        access_context_factory=None,
        uow_factory=None,
        authorization=ScopeAuthorizationService(),
        entitlement=PlanEntitlementService(DEFAULT_PLANS),
    )


async def request_app(container: ApiContainer, path: str) -> httpx.Response:
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)


async def test_health_returns_versions() -> None:
    response = await request_app(make_container("ok"), "/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["api_version"] == "1.0"
    assert "X-Request-ID" in response.headers


async def test_ready_ok_when_all_probes_pass() -> None:
    response = await request_app(make_container("ok"), "/api/v1/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


async def test_ready_503_when_database_unavailable() -> None:
    response = await request_app(make_container("failed"), "/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "failed"


async def test_ready_503_when_database_not_configured() -> None:
    response = await request_app(make_container("not_configured"), "/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "not_configured"


async def test_production_forbids_dev_auth_mode() -> None:
    with pytest.raises(RuntimeError, match="dev auth mode is forbidden"):
        build_container(ApiSettings(profile="production", auth_mode="dev"))


async def test_production_requires_database_url() -> None:
    with pytest.raises(RuntimeError, match="DW_API_DATABASE_URL"):
        build_container(
            ApiSettings(
                profile="production",
                auth_mode="oidc",
                oidc_issuer_url="https://sso.example.com/realms/dw",
                database_url=None,
            )
        )


async def test_oidc_mode_requires_issuer() -> None:
    with pytest.raises(RuntimeError, match="OIDC_ISSUER_URL"):
        build_container(ApiSettings(profile="local", auth_mode="oidc", oidc_issuer_url=None))
