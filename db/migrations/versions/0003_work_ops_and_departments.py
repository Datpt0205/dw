"""Work Operations schema + membership departments.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-23

Deferred (documented, added when their feature arrives): assignee_candidates,
dispatch_requests, follow_up_events (§19.4) — candidates/dispatch state live on
action_items for the POC slice.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

RLS_TABLES = ("meetings", "transcript_artifacts", "decisions", "action_items", "external_tasks")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS work_ops")

    # Departments enable the cross-department approval rule (§11.3).
    op.add_column(
        "memberships",
        sa.Column("department", sa.Text, nullable=False, server_default="general"),
        schema="platform",
    )

    op.create_table(
        "meetings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="created"),
        sa.Column("transcript_artifact_id", UUID(as_uuid=True), nullable=True),
        sa.Column("summary", JSONB, nullable=True),
        sa.Column("last_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="work_ops",
    )

    op.create_table(
        "transcript_artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "meeting_id",
            UUID(as_uuid=True),
            sa.ForeignKey("work_ops.meetings.id"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="work_ops",
    )

    op.create_table(
        "decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "meeting_id",
            UUID(as_uuid=True),
            sa.ForeignKey("work_ops.meetings.id"),
            nullable=False,
        ),
        sa.Column("statement", sa.Text, nullable=False),
        sa.Column("decided_by_name", sa.Text, nullable=True),
        sa.Column("evidence_quote", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="work_ops",
    )

    op.create_table(
        "action_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "meeting_id",
            UUID(as_uuid=True),
            sa.ForeignKey("work_ops.meetings.id"),
            nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("assignee_person_id", UUID(as_uuid=True), nullable=True),
        sa.Column("assignee_display_name", sa.Text, nullable=True),
        sa.Column("assignee_department", sa.Text, nullable=True),
        sa.Column("assignee_confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("due_date", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("due_date_inferred", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("risk_level", sa.Text, nullable=False, server_default="low"),
        sa.Column("status", sa.Text, nullable=False, server_default="proposed"),
        sa.Column("approval_reasons", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_quote", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="work_ops",
    )
    op.create_index(
        "ix_action_items_tenant_status",
        "action_items",
        ["tenant_id", "status"],
        schema="work_ops",
    )

    op.create_table(
        "external_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "action_item_id",
            UUID(as_uuid=True),
            sa.ForeignKey("work_ops.action_items.id"),
            nullable=False,
        ),
        sa.Column("connector", sa.Text, nullable=False),
        sa.Column("connector_version", sa.Text, nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("external_url", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Retries must never create a second external task for the same action.
        sa.UniqueConstraint("action_item_id", "connector", name="uq_external_tasks_action"),
        schema="work_ops",
    )

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE work_ops.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE work_ops.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON work_ops.{table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dw_app') THEN
                GRANT USAGE ON SCHEMA work_ops TO dw_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA work_ops TO dw_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA work_ops CASCADE")
    op.drop_column("memberships", "department", schema="platform")
