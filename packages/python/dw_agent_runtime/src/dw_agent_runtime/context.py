"""Bridging RunContext (per-run trusted context) to platform AccessContext."""

from __future__ import annotations

from dw_agent_runtime.contracts import RunContext
from dw_platform.application.access_context import AccessContext


def access_context_from_run(run_context: RunContext) -> AccessContext:
    """Derive the platform AccessContext for DB/audit work inside a run.

    The RunContext was built at the boundary from a verified AccessContext, so
    this is a projection, not an escalation.
    """
    return AccessContext(
        tenant_id=run_context.tenant_id,
        workspace_id=run_context.workspace_id,
        principal_id=run_context.actor_id,
        roles=run_context.roles,
        scopes=run_context.scopes,
        plan_id=run_context.plan_id,
    )
