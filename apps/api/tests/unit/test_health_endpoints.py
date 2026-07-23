import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings

pytestmark = pytest.mark.unit


def make_container(db_state: CheckState) -> ApiContainer:
    async def fake_db_probe() -> CheckState:
        return db_state

    return ApiContainer(
        settings=ApiSettings(profile="test"),
        engine=None,
        health_service=HealthService(probes={"database": fake_db_probe}),
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


async def test_production_profile_requires_database_url() -> None:
    from dw_api.bootstrap import build_container

    with pytest.raises(RuntimeError, match="DW_API_DATABASE_URL"):
        build_container(ApiSettings(profile="production", database_url=None))
