"""Agent runtime (worker runs, checkpoints, tool executions), knowledge, memory.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

RLS_TABLES = (
    ("platform", "worker_runs"),
    ("platform", "run_checkpoints"),
    ("platform", "run_checkpoint_writes"),
    ("platform", "tool_executions"),
    ("knowledge", "documents"),
    ("knowledge", "chunks"),
    ("memory", "items"),
    ("memory", "write_candidates"),
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    op.execute("CREATE SCHEMA IF NOT EXISTS memory")

    # ------------------------------------------------------------- runtime --
    op.create_table(
        "worker_runs",
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
        schema="platform",
    )
    op.create_index(
        "ix_worker_runs_tenant_status",
        "worker_runs",
        ["tenant_id", "status"],
        schema="platform",
    )

    op.create_table(
        "run_checkpoints",
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_ns", sa.Text, nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.Text, nullable=False),
        sa.Column("parent_checkpoint_id", sa.Text, nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("checkpoint", BYTEA, nullable=False),
        sa.Column("metadata", BYTEA, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("run_id", "checkpoint_ns", "checkpoint_id"),
        schema="platform",
    )

    op.create_table(
        "run_checkpoint_writes",
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_ns", sa.Text, nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.Text, nullable=False),
        sa.Column("task_id", sa.Text, nullable=False),
        sa.Column("idx", sa.Integer, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("value", BYTEA, nullable=False),
        sa.Column("task_path", sa.Text, nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("run_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
        schema="platform",
    )

    op.create_table(
        "tool_executions",
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
        schema="platform",
    )
    # One successful execution per (tenant, tool, idempotency key).
    op.create_index(
        "uq_tool_executions_idempotency",
        "tool_executions",
        ["tenant_id", "tool_name", "idempotency_key"],
        unique=True,
        schema="platform",
        postgresql_where=sa.text("idempotency_key IS NOT NULL AND status = 'succeeded'"),
    )

    # ----------------------------------------------------------- knowledge --
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("domain", sa.Text, nullable=False, server_default="shared"),
        sa.Column("source_uri", sa.Text, nullable=False),
        sa.Column("classification", sa.Text, nullable=False, server_default="internal"),
        sa.Column("source_version", sa.Text, nullable=False, server_default="1"),
        sa.Column("index_version", sa.Text, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="knowledge",
    )

    op.create_table(
        "chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge.documents.id"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("start_offset", sa.Integer, nullable=False),
        sa.Column("end_offset", sa.Integer, nullable=False),
        sa.Column("provenance_hash", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("document_id", "seq", name="uq_chunks_document_seq"),
        schema="knowledge",
    )

    # -------------------------------------------------------------- memory --
    op.create_table(
        "items",
        sa.Column("memory_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("worker_id", sa.Text, nullable=False),
        sa.Column("memory_type", sa.Text, nullable=False),
        sa.Column("subject_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "structured_facts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "provenance_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("classification", sa.Text, nullable=False, server_default="internal"),
        sa.Column("valid_from", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("valid_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("retention_policy", sa.Text, nullable=False, server_default="default"),
        sa.Column("memory_schema_version", sa.Text, nullable=False),
        sa.Column("created_by_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="memory",
    )

    op.create_table(
        "write_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("worker_id", sa.Text, nullable=False),
        sa.Column("memory_type", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "structured_facts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "provenance_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("classification", sa.Text, nullable=False, server_default="internal"),
        sa.Column("decision", sa.Text, nullable=False),
        sa.Column("memory_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="memory",
    )

    # ----------------------------------------------------------------- RLS --
    for schema, table in RLS_TABLES:
        op.execute(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {schema}.{table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )

    # -------------------------------------------------------------- grants --
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dw_app') THEN
                GRANT USAGE ON SCHEMA platform, knowledge, memory TO dw_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA platform, knowledge, memory TO dw_app;
                REVOKE UPDATE, DELETE ON platform.audit_events FROM dw_app;
                REVOKE UPDATE, DELETE ON platform.approval_decisions FROM dw_app;
                REVOKE UPDATE, DELETE ON platform.tool_executions FROM dw_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA memory CASCADE")
    op.execute("DROP SCHEMA knowledge CASCADE")
    for table in ("tool_executions", "run_checkpoint_writes", "run_checkpoints", "worker_runs"):
        op.drop_table(table, schema="platform")
