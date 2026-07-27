"""Durable Slack notification queue and DW01 intake rejection state.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_notification_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "case_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tender.preparation_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("recipient_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="5"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("slack_channel_id", sa.Text, nullable=True),
        sa.Column("slack_message_ts", sa.Text, nullable=True),
        sa.Column("claimed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('queued','processing','sent','failed','cancelled')",
            name="ck_approval_notification_job_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_approval_notification_attempts"),
        sa.CheckConstraint("max_attempts > 0", name="ck_approval_notification_max_attempts"),
        schema="tender",
    )
    op.create_index(
        "ix_approval_notification_due",
        "approval_notification_jobs",
        ["status", "due_at"],
        schema="tender",
    )
    op.create_index(
        "ix_approval_notification_case",
        "approval_notification_jobs",
        ["tenant_id", "case_id", "created_at"],
        schema="tender",
    )

    op.execute("ALTER TABLE tender.approval_notification_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tender.approval_notification_jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_approval_notification_jobs
        ON tender.approval_notification_jobs
        USING (
          tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (
          tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY worker_drain_approval_notification_jobs
        ON tender.approval_notification_jobs
        USING (current_setting('app.worker_drain', true) = 'on')
        WITH CHECK (current_setting('app.worker_drain', true) = 'on')
        """
    )
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE
        ON tender.approval_notification_jobs TO dw_app
        """
    )

    # The notification worker reads case state under the same narrowly-scoped
    # worker GUC before sending a due reminder. It cannot mutate cases.
    op.execute(
        """
        CREATE POLICY worker_read_preparation_cases
        ON tender.preparation_cases
        FOR SELECT
        USING (current_setting('app.worker_drain', true) = 'on')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS worker_read_preparation_cases ON tender.preparation_cases")
    op.execute(
        "DROP POLICY IF EXISTS worker_drain_approval_notification_jobs "
        "ON tender.approval_notification_jobs"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_approval_notification_jobs "
        "ON tender.approval_notification_jobs"
    )
    op.drop_index(
        "ix_approval_notification_case",
        table_name="approval_notification_jobs",
        schema="tender",
    )
    op.drop_index(
        "ix_approval_notification_due",
        table_name="approval_notification_jobs",
        schema="tender",
    )
    op.drop_table("approval_notification_jobs", schema="tender")
