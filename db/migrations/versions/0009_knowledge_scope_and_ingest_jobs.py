"""Knowledge document scope (global vs tenant) + async ingest jobs (B5).

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-25

- ``documents.scope`` persists whether a document is tenant-private or a GLOBAL
  legal document shared across every tenant. A permissive SELECT policy lets any
  tenant READ global rows, while writes stay tenant-isolated (WITH CHECK on the
  original FOR ALL policy is unchanged — no cross-tenant writes).
- ``ingest_jobs`` is the durable queue the API writes on upload and the worker
  drains to run parse(OCR) → chunk → embed → index off the request path.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- documents.scope ---------------------------------------------------
    op.add_column(
        "documents",
        sa.Column("scope", sa.Text, nullable=False, server_default="tenant"),
        schema="knowledge",
    )
    op.create_index(
        "ix_documents_scope",
        "documents",
        ["scope", "status"],
        schema="knowledge",
    )
    # Permissive SELECT policy: OR-ed with tenant_isolation_documents, so a read
    # succeeds when the row is own-tenant OR globally scoped. Writes are NOT
    # widened — the original FOR ALL policy's WITH CHECK still requires own tenant.
    op.execute(
        """
        CREATE POLICY knowledge_global_read_documents ON knowledge.documents
        FOR SELECT
        USING (scope = 'global')
        """
    )

    # --- ingest_jobs (durable upload queue) --------------------------------
    op.create_table(
        "ingest_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("domain", sa.Text, nullable=False, server_default="shared"),
        sa.Column("classification", sa.Text, nullable=False, server_default="internal"),
        sa.Column("source_version", sa.Text, nullable=False, server_default="1"),
        sa.Column("scope", sa.Text, nullable=False, server_default="tenant"),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        # queued -> processing -> done | failed
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=True),
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
        schema="knowledge",
    )
    op.create_index(
        "ix_ingest_jobs_status",
        "ingest_jobs",
        ["status", "created_at"],
        schema="knowledge",
    )
    op.execute("ALTER TABLE knowledge.ingest_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge.ingest_jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_ingest_jobs ON knowledge.ingest_jobs
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )
    # The worker drains the queue across tenants; it sets app.tenant_id per job,
    # but the initial "claim" scan reads all tenants. Allow a dedicated worker
    # bypass via a GUC flag so the durable queue can be polled globally.
    op.execute(
        """
        CREATE POLICY worker_drain_ingest_jobs ON knowledge.ingest_jobs
        FOR SELECT
        USING (current_setting('app.worker_drain', true) = 'on')
        """
    )
    # The 0002 grant was a one-time snapshot; a table created later needs its own.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dw_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON knowledge.ingest_jobs TO dw_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS worker_drain_ingest_jobs ON knowledge.ingest_jobs")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_ingest_jobs ON knowledge.ingest_jobs")
    op.drop_index("ix_ingest_jobs_status", table_name="ingest_jobs", schema="knowledge")
    op.drop_table("ingest_jobs", schema="knowledge")

    op.execute("DROP POLICY IF EXISTS knowledge_global_read_documents ON knowledge.documents")
    op.drop_index("ix_documents_scope", table_name="documents", schema="knowledge")
    op.drop_column("documents", "scope", schema="knowledge")
