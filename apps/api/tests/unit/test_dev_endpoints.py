"""Dev demo endpoints: one-click login works in dev, absent in production."""

from __future__ import annotations

import httpx
import pytest

from dw_api.bootstrap import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings

pytestmark = pytest.mark.unit

DEV_SECRET = "unit-test-dev-secret-0123456789abcdef"


def make_app(auth_mode: str = "dev"):
    settings = ApiSettings(
        profile="test",
        auth_mode=auth_mode,  # type: ignore[arg-type]
        dev_secret=DEV_SECRET,
        oidc_issuer_url="https://keycloak.example/realms/dw" if auth_mode == "oidc" else None,
        rate_limit_per_minute=0,
    )
    return create_app(build_container(settings))


async def _get(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def _post(app, path: str, body: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body)


async def test_demo_users_listed_in_dev_mode() -> None:
    response = await _get(make_app(), "/api/v1/dev/demo-users")
    assert response.status_code == 200
    subjects = {user["subject"] for user in response.json()}
    assert {"dev|an.nguyen", "dev|binh.tran", "dev|bao.pham"} <= subjects


async def test_session_issues_verifiable_token_with_context() -> None:
    from dw_platform.adapters.identity.dev_token import DevTokenVerifier

    response = await _post(make_app(), "/api/v1/dev/session", {"subject": "dev|an.nguyen"})
    assert response.status_code == 200
    session = response.json()
    assert session["display_name"] == "Nguyễn Văn An"
    assert session["tenant_name"] == "Công ty Alpha"
    claims = await DevTokenVerifier(DEV_SECRET).verify(session["token"])
    assert claims.subject == "dev|an.nguyen"


async def test_unknown_subject_is_rejected() -> None:
    response = await _post(make_app(), "/api/v1/dev/session", {"subject": "dev|hacker"})
    assert response.status_code == 404


async def test_dev_routes_absent_outside_dev_auth_mode() -> None:
    response = await _get(make_app(auth_mode="oidc"), "/api/v1/dev/demo-users")
    assert response.status_code == 404
