"""SQLAlchemy Core tables for the work_ops schema (mirrors migration 0003)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(schema="work_ops")

meetings = sa.Table(
    "meetings",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("transcript_artifact_id", UUID(as_uuid=True), nullable=True),
    sa.Column("summary", JSONB, nullable=True),
    sa.Column("last_run_id", UUID(as_uuid=True), nullable=True),
    sa.Column("created_by", UUID(as_uuid=True), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

transcript_artifacts = sa.Table(
    "transcript_artifacts",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("meeting_id", UUID(as_uuid=True), nullable=False),
    sa.Column("storage_key", sa.Text, nullable=False),
    sa.Column("filename", sa.Text, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("uploaded_by", UUID(as_uuid=True), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

decisions = sa.Table(
    "decisions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("meeting_id", UUID(as_uuid=True), nullable=False),
    sa.Column("statement", sa.Text, nullable=False),
    sa.Column("decided_by_name", sa.Text, nullable=True),
    sa.Column("evidence_quote", sa.Text, nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

action_items = sa.Table(
    "action_items",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("meeting_id", UUID(as_uuid=True), nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("assignee_person_id", UUID(as_uuid=True), nullable=True),
    sa.Column("assignee_display_name", sa.Text, nullable=True),
    sa.Column("assignee_department", sa.Text, nullable=True),
    sa.Column("assignee_confidence", sa.Float, nullable=False),
    sa.Column("due_date", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("due_date_inferred", sa.Boolean, nullable=False),
    sa.Column("risk_level", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("approval_reasons", JSONB, nullable=False),
    sa.Column("source_quote", sa.Text, nullable=True),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

external_tasks = sa.Table(
    "external_tasks",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("action_item_id", UUID(as_uuid=True), nullable=False),
    sa.Column("connector", sa.Text, nullable=False),
    sa.Column("connector_version", sa.Text, nullable=False),
    sa.Column("external_id", sa.Text, nullable=False),
    sa.Column("external_url", sa.Text, nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
)
