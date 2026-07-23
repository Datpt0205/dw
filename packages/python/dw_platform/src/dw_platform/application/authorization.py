"""Scope-based authorization service (implements ``AuthorizationPort``).

Authorization is deliberately separate from entitlement (§15.1): this answers
"may this principal do this action", never "does the plan include it".
"""

from __future__ import annotations

from dataclasses import dataclass

from dw_kernel.errors import PermissionDeniedError
from dw_platform.application.access_context import AccessContext

PLATFORM_ADMIN_ROLE = "platform_admin"


@dataclass(frozen=True)
class ScopeAuthorizationService:
    """RBAC via scopes resolved from roles at context-build time.

    ABAC refinements (ownership, department, classification) layer on top as
    domain policy objects in each bounded context; this service is the baseline
    route/tool gate.
    """

    admin_role: str = PLATFORM_ADMIN_ROLE

    async def require(
        self,
        *,
        context: AccessContext,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
    ) -> None:
        if self.is_allowed(context, action):
            return
        raise PermissionDeniedError(
            "action not permitted",
            details={
                "action": action,
                "resource_type": resource_type,
                **({"resource_id": resource_id} if resource_id else {}),
            },
        )

    def is_allowed(self, context: AccessContext, action: str) -> bool:
        if self.admin_role in context.roles:
            return True
        return action in context.scopes
