"""SQLAlchemy Core tables for runtime persistence (mirrors migration 0002)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID

metadata = sa.MetaData(schema="platform")

worker_runs = sa.Table(
    "worker_runs",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("worker_id", sa.Text, nullable=False),
    sa.Column("worker_version", sa.Text, nullable=False),
    sa.Column("graph_version", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="pending"),
    sa.Column("input", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("result", JSONB, nullable=True),
    sa.Column("error", JSONB, nullable=True),
    sa.Column("approval_request_id", UUID(as_uuid=True), nullable=True),
    sa.Column("release_manifest_ref", sa.Text, nullable=True),
    sa.Column("requested_by", UUID(as_uuid=True), nullable=False),
    sa.Column("trace_id", sa.Text, nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

run_checkpoints = sa.Table(
    "run_checkpoints",
    metadata,
    sa.Column("run_id", UUID(as_uuid=True), nullable=False),
    sa.Column("checkpoint_ns", sa.Text, nullable=False),
    sa.Column("checkpoint_id", sa.Text, nullable=False),
    sa.Column("parent_checkpoint_id", sa.Text, nullable=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("checkpoint", BYTEA, nullable=False),
    sa.Column("metadata", BYTEA, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("run_id", "checkpoint_ns", "checkpoint_id"),
)

run_checkpoint_writes = sa.Table(
    "run_checkpoint_writes",
    metadata,
    sa.Column("run_id", UUID(as_uuid=True), nullable=False),
    sa.Column("checkpoint_ns", sa.Text, nullable=False),
    sa.Column("checkpoint_id", sa.Text, nullable=False),
    sa.Column("task_id", sa.Text, nullable=False),
    sa.Column("idx", sa.Integer, nullable=False),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("channel", sa.Text, nullable=False),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("value", BYTEA, nullable=False),
    sa.Column("task_path", sa.Text, nullable=False),
    sa.PrimaryKeyConstraint("run_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
)

tool_executions = sa.Table(
    "tool_executions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("run_id", UUID(as_uuid=True), nullable=True),
    sa.Column("tool_name", sa.Text, nullable=False),
    sa.Column("tool_version", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("idempotency_key", sa.Text, nullable=True),
    sa.Column("input_hash", sa.Text, nullable=False),
    sa.Column("output_hash", sa.Text, nullable=True),
    sa.Column("output", JSONB, nullable=True),
    sa.Column("error", sa.Text, nullable=True),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
)
