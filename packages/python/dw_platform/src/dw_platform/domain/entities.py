"""Platform domain entities: tenancy, membership, plans (blueprint §15).

Pure dataclasses with invariants — no framework imports (enforced by
architecture tests).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from dw_kernel.ids import EntityId, TenantId, UserId, WorkspaceId

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


def _require_slug(value: str, owner: str) -> str:
    if not _SLUG_PATTERN.fullmatch(value):
        raise ValueError(f"{owner} slug must match {_SLUG_PATTERN.pattern}, got {value!r}")
    return value


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


@dataclass(slots=True)
class Tenant:
    id: TenantId
    slug: str
    name: str
    status: TenantStatus = TenantStatus.ACTIVE

    def __post_init__(self) -> None:
        _require_slug(self.slug, "tenant")
        if not self.name.strip():
            raise ValueError("tenant name must not be blank")


@dataclass(slots=True)
class Workspace:
    id: WorkspaceId
    tenant_id: TenantId
    slug: str
    name: str

    def __post_init__(self) -> None:
        _require_slug(self.slug, "workspace")
        if not self.name.strip():
            raise ValueError("workspace name must not be blank")


@dataclass(slots=True)
class User:
    """A platform user; identity comes from the verified token subject."""

    id: UserId
    subject: str
    email: str | None
    display_name: str

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("user subject must not be blank")
        if not self.display_name.strip():
            raise ValueError("user display_name must not be blank")


@dataclass(frozen=True, slots=True)
class Role:
    """A named bundle of scopes. Role keys are stable identifiers."""

    key: str
    name: str
    scopes: frozenset[str]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", self.key):
            raise ValueError(f"role key must be snake_case, got {self.key!r}")


@dataclass(slots=True)
class Membership:
    """Grants a user access to one workspace of one tenant with roles."""

    id: EntityId
    tenant_id: TenantId
    workspace_id: WorkspaceId
    user_id: UserId
    role_keys: frozenset[str]
    clearance: str = "internal"

    def __post_init__(self) -> None:
        if not self.role_keys:
            raise ValueError("membership requires at least one role")


@dataclass(frozen=True, slots=True)
class Plan:
    """A subscription plan: features + quotas. Entitlement != authorization."""

    plan_id: str
    name: str
    features: frozenset[str]
    quotas: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError("plan_id must not be blank")
        for key, value in self.quotas.items():
            if value < 0:
                raise ValueError(f"quota {key!r} must be >= 0")


@dataclass(slots=True)
class Entitlement:
    """Binds a tenant to a plan, with optional per-tenant feature overrides."""

    id: EntityId
    tenant_id: TenantId
    plan_id: str
    feature_overrides: frozenset[str] = frozenset()

    def effective_features(self, plan: Plan) -> frozenset[str]:
        if plan.plan_id != self.plan_id:
            raise ValueError("plan does not match entitlement")
        return plan.features | self.feature_overrides
