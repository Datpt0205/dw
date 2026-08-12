"""SQLAlchemy Core tables for DW01 preparation (schema ``tender``).

Mirrors migration 0007 — change both together.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(schema="tender")

preparation_cases = sa.Table(
    "preparation_cases",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("description", sa.Text, nullable=False, server_default=""),
    sa.Column("source_pr_ref", sa.Text, nullable=False, server_default=""),
    sa.Column("estimated_value_minor", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("currency", sa.Text, nullable=False, server_default="VND"),
    sa.Column("deadline", sa.Text, nullable=True),
    sa.Column("owner_name", sa.Text, nullable=False, server_default=""),
    sa.Column("procurement_type", sa.Text, nullable=False, server_default="other"),
    sa.Column("business_domain", sa.Text, nullable=False, server_default="general"),
    sa.Column("method_key", sa.Text, nullable=True),
    sa.Column("state", sa.Text, nullable=False, server_default="draft"),
    sa.Column("current_step", sa.Text, nullable=False, server_default="intake"),
    sa.Column("last_run_id", UUID(as_uuid=True), nullable=True),
    sa.Column("current_official_artifact_id", UUID(as_uuid=True), nullable=True),
    sa.Column("export_ref", sa.Text, nullable=True),
    sa.Column("intake_verified_by", UUID(as_uuid=True), nullable=True),
    sa.Column("intake_verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("bids_close_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_by", UUID(as_uuid=True), nullable=False),
    sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
    sa.Column(
        "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
)

preparation_documents = sa.Table(
    "preparation_documents",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("case_id", UUID(as_uuid=True), nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("filename", sa.Text, nullable=False),
    sa.Column("content_type", sa.Text, nullable=False),
    sa.Column("size_bytes", sa.BigInteger, nullable=False),
    sa.Column("storage_key", sa.Text, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("uploaded_by", UUID(as_uuid=True), nullable=False),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
)

preparation_artifacts = sa.Table(
    "preparation_artifacts",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("case_id", UUID(as_uuid=True), nullable=False),
    sa.Column("artifact_type", sa.Text, nullable=False),
    sa.Column("schema_version", sa.Text, nullable=False, server_default="1.0"),
    sa.Column("artifact_version", sa.Integer, nullable=False, server_default="1"),
    sa.Column("status", sa.Text, nullable=False, server_default="draft"),
    sa.Column("content_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("evidence_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("source_artifact_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("content_hash", sa.Text, nullable=False, server_default=""),
    sa.Column("created_by", UUID(as_uuid=True), nullable=False),
    sa.Column(
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
    sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
)

approval_notification_jobs = sa.Table(
    "approval_notification_jobs",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column(
        "case_id",
        UUID(as_uuid=True),
        sa.ForeignKey("preparation_cases.id", ondelete="CASCADE"),
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
        "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
    sa.Column(
        "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    ),
)
