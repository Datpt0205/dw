"""Trusted access context built at the boundary (blueprint §15.2).

The context is constructed only from a verified token plus database membership.
It is passed explicitly; domain/application code never reads tenant or user
identity from globals, headers or model output.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class AccessContext(BaseModel):
    """Immutable, verified identity + tenancy + entitlement snapshot."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    workspace_id: UUID
    principal_id: UUID
    roles: frozenset[str]
    groups: frozenset[str] = frozenset()
    scopes: frozenset[str] = frozenset()
    clearance: str = "internal"
    plan_id: str
    feature_flags: frozenset[str] = frozenset()

    @field_validator("plan_id", "clearance")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def has_any_role(self, *roles: str) -> bool:
        return any(role in self.roles for role in roles)

    def has_feature(self, flag: str) -> bool:
        return flag in self.feature_flags
