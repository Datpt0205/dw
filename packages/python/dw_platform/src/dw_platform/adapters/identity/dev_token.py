"""Local development token verifier (ADR-013).

HS256 JWTs signed with a shared dev secret. Wired ONLY in local/test profiles;
the production composition root must refuse this adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from dw_kernel.errors import PermissionDeniedError
from dw_platform.application.identity import VerifiedClaims

DEV_ISSUER = "dw-dev"
DEV_AUDIENCE = "dw-api"


@dataclass(frozen=True)
class DevTokenVerifier:
    """Implements ``TokenVerifierPort`` for local development and tests."""

    secret: str
    issuer: str = DEV_ISSUER
    audience: str = DEV_AUDIENCE

    def __post_init__(self) -> None:
        if len(self.secret) < 32:
            raise ValueError("dev token secret must be at least 32 characters")

    async def verify(self, token: str) -> VerifiedClaims:
        try:
            claims = jwt.decode(
                token,
                key=self.secret,
                algorithms=["HS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise PermissionDeniedError(
                "invalid bearer token", details={"reason": type(exc).__name__}
            ) from exc
        return VerifiedClaims(
            subject=str(claims["sub"]),
            email=claims.get("email"),
            issuer=str(claims["iss"]),
        )

    def issue(
        self,
        subject: str,
        *,
        email: str | None = None,
        ttl: timedelta = timedelta(hours=8),
    ) -> str:
        """Issue a dev token (used by seed output and tests)."""
        now = datetime.now(tz=UTC)
        payload: dict[str, object] = {
            "sub": subject,
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
        }
        if email:
            payload["email"] = email
        return jwt.encode(payload, key=self.secret, algorithm="HS256")
