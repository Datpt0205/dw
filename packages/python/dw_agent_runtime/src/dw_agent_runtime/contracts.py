"""Immutable, versioned runtime contracts (blueprint §10).

Changing a prompt, tool or graph requires a new version — these models are
frozen and carry explicit version fields that feed the release manifest.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"

AutonomyLevel = Literal["A0", "A1", "A2", "A3", "A4"]
SideEffectLevel = Literal["none", "internal", "external", "critical"]
ApprovalPolicy = Literal["never", "conditional", "always"]
WorkerDomain = Literal["tender", "work_ops", "preparation"]


class WorkerDefinition(BaseModel):
    """Immutable description of a deployable Digital Worker."""

    model_config = ConfigDict(frozen=True)

    worker_id: str
    worker_version: str = Field(pattern=_SEMVER_PATTERN)
    domain: WorkerDomain
    graph_version: str = Field(pattern=_SEMVER_PATTERN)
    prompt_bundle_version: str = Field(pattern=_SEMVER_PATTERN)
    toolset_version: str = Field(pattern=_SEMVER_PATTERN)
    policy_version: str = Field(pattern=_SEMVER_PATTERN)
    memory_policy_version: str = Field(pattern=_SEMVER_PATTERN)
    default_model_profile: str
    supported_channels: frozenset[str]
    autonomy_level: AutonomyLevel

    @field_validator("worker_id", "default_model_profile")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class RunContext(BaseModel):
    """Per-run trusted context, created at the boundary and passed explicitly."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    actor_id: UUID
    worker_id: str
    worker_version: str = Field(pattern=_SEMVER_PATTERN)
    channel: str
    plan_id: str
    roles: frozenset[str]
    scopes: frozenset[str]
    trace_id: str
    locale: str = "vi-VN"


class ToolDefinition(BaseModel):
    """Versioned tool contract enforced by the tool executor."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str = Field(pattern=_SEMVER_PATTERN)
    description: str
    input_schema_ref: str
    output_schema_ref: str
    required_scopes: frozenset[str]
    side_effect_level: SideEffectLevel
    approval_policy: ApprovalPolicy
    timeout_seconds: int = Field(gt=0, le=600)
    max_retries: int = Field(ge=0, le=10)
    idempotent: bool
    data_classification: frozenset[str]

    @field_validator("name")
    @classmethod
    def _tool_name_is_namespaced(cls, value: str) -> str:
        if "." not in value or value.startswith(".") or value.endswith("."):
            raise ValueError("tool name must be namespaced like 'task.prepare'")
        return value

    def requires_approval(self) -> bool:
        """Critical side effects always require approval regardless of policy."""
        return self.approval_policy == "always" or self.side_effect_level == "critical"
