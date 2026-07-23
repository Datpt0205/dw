"""SQLAlchemy Core table definitions for the platform schema.

Imperative (non-ORM) mapping keeps the domain free of SQLAlchemy; repositories
translate rows <-> domain objects explicitly. Mirrors the Alembic migration —
change both together.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(schema="platform")

tenants = sa.Table(
    "tenants",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("slug", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="active"),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
)

workspaces = sa.Table(
    "workspaces",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
    sa.Column("slug", sa.Text, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
    sa.UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),
)

users = sa.Table(
    "users",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("subject", sa.Text, nullable=False, unique=True),
    sa.Column("email", sa.Text, nullable=True, unique=True),
    sa.Column("display_name", sa.Text, nullable=False),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
)

roles = sa.Table(
    "roles",
    metadata,
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("scopes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
)

plans = sa.Table(
    "plans",
    metadata,
    sa.Column("plan_id", sa.Text, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("features", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("quotas", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
)

memberships = sa.Table(
    "memberships",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
    sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("role_keys", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("clearance", sa.Text, nullable=False, server_default="internal"),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
    sa.UniqueConstraint("tenant_id", "workspace_id", "user_id", name="uq_memberships_scope_user"),
)

entitlements = sa.Table(
    "entitlements",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True
    ),
    sa.Column("plan_id", sa.Text, sa.ForeignKey("plans.plan_id"), nullable=False),
    sa.Column("feature_overrides", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
)

approval_requests = sa.Table(
    "approval_requests",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("approval_type", sa.Text, nullable=False),
    sa.Column("requested_by", UUID(as_uuid=True), nullable=False),
    sa.Column("reason", sa.Text, nullable=False, server_default=""),
    sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("run_id", UUID(as_uuid=True), nullable=True),
    sa.Column("status", sa.Text, nullable=False, server_default="pending"),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
    sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("version", sa.Integer, nullable=False, server_default="1"),
)

approval_decisions = sa.Table(
    "approval_decisions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "request_id", UUID(as_uuid=True), sa.ForeignKey("approval_requests.id"), nullable=False
    ),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("decided_by", UUID(as_uuid=True), nullable=False),
    sa.Column("outcome", sa.Text, nullable=False),
    sa.Column("comment", sa.Text, nullable=False, server_default=""),
    sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

audit_events = sa.Table(
    "audit_events",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("actor_id", UUID(as_uuid=True), nullable=False),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("resource_type", sa.Text, nullable=False),
    sa.Column("resource_id", sa.Text, nullable=False),
    sa.Column("run_id", UUID(as_uuid=True), nullable=True),
    sa.Column("policy_decision", sa.Text, nullable=True),
    sa.Column("trace_id", sa.Text, nullable=True),
    sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

outbox_events = sa.Table(
    "outbox_events",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("event_type", sa.Text, nullable=False),
    sa.Column("schema_version", sa.Text, nullable=False),
    sa.Column("aggregate_id", UUID(as_uuid=True), nullable=False),
    sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("correlation_id", UUID(as_uuid=True), nullable=True),
    sa.Column("causation_id", UUID(as_uuid=True), nullable=True),
    sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
    sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
)

# Tables whose rows belong to exactly one tenant → RLS enabled + forced.
TENANT_SCOPED_TABLES = (
    "workspaces",
    "memberships",
    "entitlements",
    "approval_requests",
    "approval_decisions",
    "audit_events",
    "outbox_events",
)
