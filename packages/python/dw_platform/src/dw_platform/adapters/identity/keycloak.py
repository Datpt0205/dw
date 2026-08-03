"""Keycloak OIDC token verifier (ADR-013).

RS256 verification against the realm JWKS endpoint. PyJWKClient performs
blocking HTTP, so verification runs in a worker thread.
"""

from __future__ import annotations

import asyncio
from functools import cached_property

import jwt
from jwt import PyJWKClient

from dw_kernel.errors import PermissionDeniedError
from dw_platform.application.identity import VerifiedClaims


class KeycloakTokenVerifier:
    """Implements ``TokenVerifierPort`` against a Keycloak realm."""

    def __init__(
        self,
        issuer_url: str,
        audience: str = "dw-api",
        jwks_url: str | None = None,
    ) -> None:
        if not issuer_url.startswith(("http://", "https://")):
            raise ValueError("issuer_url must be an http(s) URL")
        self._issuer_url = issuer_url.rstrip("/")
        self._audience = audience
        # In Docker the API reaches Keycloak at a different host than the
        # browser-facing issuer, so the JWKS URL can be supplied separately.
        self._jwks_url = jwks_url or f"{self._issuer_url}/protocol/openid-connect/certs"

    @cached_property
    def _jwks_client(self) -> PyJWKClient:
        return PyJWKClient(self._jwks_url, cache_keys=True, lifespan=300)

    def _verify_sync(self, token: str) -> VerifiedClaims:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=["RS256"],
                issuer=self._issuer_url,
                audience=self._audience,
                options={"require": ["exp", "iss", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise PermissionDeniedError(
                "invalid bearer token", details={"reason": type(exc).__name__}
            ) from exc
        return VerifiedClaims(
            subject=str(claims["sub"]),
            email=claims.get("email"),
            issuer=str(claims["iss"]),
            name=claims.get("name") or claims.get("preferred_username"),
        )

    async def verify(self, token: str) -> VerifiedClaims:
        return await asyncio.to_thread(self._verify_sync, token)
