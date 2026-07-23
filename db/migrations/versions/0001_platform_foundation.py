"""Platform foundation: tenancy, membership, plans, approval, audit, outbox + RLS.

Revision ID: 0001
Revises:
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Tables whose rows belong to exactly one tenant → RLS enabled + FORCED.
TENANT_SCOPED = (
    "workspaces",
    "memberships",
    "entitlements",
    "approval_requests",
    "approval_decisions",
    "audit_events",
    "outbox_events",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS platform")

    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="platform",
    )

    op.create_table(
        "workspaces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.tenants.id"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),
        schema="platform",
    )

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("subject", sa.Text, nullable=False, unique=True),
        sa.Column("email", sa.Text, nullable=True, unique=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="platform",
    )

    op.create_table(
        "roles",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("scopes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        schema="platform",
    )

    op.create_table(
        "plans",
        sa.Column("plan_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("features", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("quotas", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="platform",
    )

    op.create_table(
        "memberships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.workspaces.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id", UUID(as_uuid=True), sa.ForeignKey("platform.users.id"), nullable=False
        ),
        sa.Column("role_keys", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("clearance", sa.Text, nullable=False, server_default="internal"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "workspace_id", "user_id", name="uq_memberships_scope_user"
        ),
        schema="platform",
    )
    op.create_index(
        "ix_memberships_tenant_user", "memberships", ["tenant_id", "user_id"], schema="platform"
    )

    op.create_table(
        "entitlements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.tenants.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "plan_id", sa.Text, sa.ForeignKey("platform.plans.plan_id"), nullable=False
        ),
        sa.Column(
            "feature_overrides", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        schema="platform",
    )

    op.create_table(
        "approval_requests",
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
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        schema="platform",
    )
    op.create_index(
        "ix_approval_requests_tenant_status",
        "approval_requests",
        ["tenant_id", "status"],
        schema="platform",
    )

    op.create_table(
        "approval_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "request_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.approval_requests.id"),
            nullable=False,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("decided_by", UUID(as_uuid=True), nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("comment", sa.Text, nullable=False, server_default=""),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=False),
        schema="platform",
    )

    op.create_table(
        "audit_events",
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
        schema="platform",
    )
    op.create_index(
        "ix_audit_events_tenant_time",
        "audit_events",
        ["tenant_id", "occurred_at"],
        schema="platform",
    )

    op.create_table(
        "outbox_events",
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
        schema="platform",
    )
    op.create_index(
        "ix_outbox_events_unprocessed",
        "outbox_events",
        ["occurred_at"],
        schema="platform",
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    # ------------------------------------------------------------------ RLS --
    # The tenants table restricts rows to the tenant in context.
    op.execute("ALTER TABLE platform.tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_tenants ON platform.tenants
        USING (id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (id = current_setting('app.tenant_id', true)::uuid)
        """
    )
    for table in TENANT_SCOPED:
        op.execute(f"ALTER TABLE platform.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE platform.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON platform.{table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )

    # ---------------------------------------------------------------- grants --
    # Runtime role: full DML except audit is append-only. Guarded so the
    # migration also applies on databases without the role (e.g. plain CI).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dw_app') THEN
                GRANT USAGE ON SCHEMA platform TO dw_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA platform TO dw_app;
                REVOKE UPDATE, DELETE ON platform.audit_events FROM dw_app;
                REVOKE UPDATE, DELETE ON platform.approval_decisions FROM dw_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA platform CASCADE")
