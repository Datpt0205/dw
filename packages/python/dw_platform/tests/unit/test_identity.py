import uuid

import pytest

from dw_kernel.errors import PermissionDeniedError, TenantContextMissingError
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.identity import (
    DbAccessContextFactory,
    MembershipAccess,
    VerifiedClaims,
)

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
PRINCIPAL = uuid.uuid4()


class FakeMembershipLookup:
    """Grants access only for one known (subject, tenant, workspace) triple."""

    def __init__(self, known_subject: str = "dev|an.nguyen") -> None:
        self.known_subject = known_subject

    async def find_access(
        self, subject: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        if subject == self.known_subject and tenant_id == TENANT and workspace_id == WORKSPACE:
            return MembershipAccess(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                principal_id=PRINCIPAL,
                roles=frozenset({"member"}),
                scopes=frozenset({"work_ops.read"}),
                groups=frozenset(),
                clearance="internal",
                plan_id="professional",
                feature_flags=frozenset({"tender_worker"}),
            )
        return None


CLAIMS = VerifiedClaims(subject="dev|an.nguyen", email="an@alpha.local", issuer="dw-dev")


async def test_builds_context_from_confirmed_membership() -> None:
    factory = DbAccessContextFactory(FakeMembershipLookup())
    context = await factory.build(CLAIMS, TENANT, WORKSPACE)
    assert context.tenant_id == TENANT
    assert context.principal_id == PRINCIPAL
    assert context.plan_id == "professional"
    assert context.has_feature("tender_worker")


async def test_missing_tenant_header_rejected() -> None:
    factory = DbAccessContextFactory(FakeMembershipLookup())
    with pytest.raises(TenantContextMissingError):
        await factory.build(CLAIMS, None, WORKSPACE)


async def test_requested_tenant_is_not_trusted_without_membership() -> None:
    """A valid token asking for another tenant gets denied — the DB decides."""
    factory = DbAccessContextFactory(FakeMembershipLookup())
    other_tenant = uuid.uuid4()
    with pytest.raises(PermissionDeniedError):
        await factory.build(CLAIMS, other_tenant, WORKSPACE)


async def test_unknown_subject_denied() -> None:
    factory = DbAccessContextFactory(FakeMembershipLookup(known_subject="dev|someone.else"))
    with pytest.raises(PermissionDeniedError):
        await factory.build(CLAIMS, TENANT, WORKSPACE)


# --- dev token verifier -----------------------------------------------------


async def test_dev_token_roundtrip() -> None:
    verifier = DevTokenVerifier("unit-test-secret-0123456789abcdef")
    token = verifier.issue("dev|an.nguyen", email="an@alpha.local")
    claims = await verifier.verify(token)
    assert claims.subject == "dev|an.nguyen"
    assert claims.email == "an@alpha.local"
    assert claims.issuer == "dw-dev"


async def test_dev_token_bad_signature_rejected() -> None:
    token = DevTokenVerifier("unit-test-secret-0123456789abcdef").issue("dev|an.nguyen")
    other = DevTokenVerifier("another-secret-0123456789abcdefgh")
    with pytest.raises(PermissionDeniedError):
        await other.verify(token)


async def test_dev_token_expired_rejected() -> None:
    from datetime import timedelta

    verifier = DevTokenVerifier("unit-test-secret-0123456789abcdef")
    token = verifier.issue("dev|an.nguyen", ttl=timedelta(seconds=-10))
    with pytest.raises(PermissionDeniedError):
        await verifier.verify(token)


def test_dev_verifier_requires_strong_enough_secret() -> None:
    with pytest.raises(ValueError, match="32"):
        DevTokenVerifier("short")
