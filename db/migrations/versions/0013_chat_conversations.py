"""Chat front-office: conversation state + channel event dedupe.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-31

``tender.chat_conversations`` — one row per Slack DM/thread intake session:
slot state collected through dialogue, lifecycle
(collecting → confirming → case_created | cancelled) and the resulting case.
Tenant-scoped → RLS forced, same policy shape as other tender tables.

``platform.channel_event_dedupe`` — at-least-once inbound channel events
(Slack retries/socket redeliveries) are claimed by primary-key insert *before*
tenant resolution, so this lives on the channel/identity plane without RLS —
same rationale as ``platform.external_identities``. Content is only an opaque
provider event id.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("channel_key", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="collecting"),
        sa.Column("slots", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("case_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('collecting', 'confirming', 'case_created', 'cancelled')",
            name="ck_chat_conversations_state",
        ),
        schema="tender",
    )
    # One in-flight intake per channel/thread per workspace.
    op.create_index(
        "uq_chat_conversations_active_channel",
        "chat_conversations",
        ["tenant_id", "workspace_id", "channel_key"],
        unique=True,
        schema="tender",
        postgresql_where=sa.text("state IN ('collecting', 'confirming')"),
    )

    op.execute("ALTER TABLE tender.chat_conversations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tender.chat_conversations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_chat_conversations
        ON tender.chat_conversations
        USING (
          tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (
          tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        """
    )

    op.create_table(
        "channel_event_dedupe",
        sa.Column("event_id", sa.Text, primary_key=True),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        schema="platform",
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dw_app') THEN
                GRANT SELECT, INSERT, UPDATE ON tender.chat_conversations TO dw_app;
                GRANT SELECT, INSERT ON platform.channel_event_dedupe TO dw_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("channel_event_dedupe", schema="platform")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_chat_conversations ON tender.chat_conversations"
    )
    op.drop_index(
        "uq_chat_conversations_active_channel",
        table_name="chat_conversations",
        schema="tender",
    )
    op.drop_table("chat_conversations", schema="tender")
