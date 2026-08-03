"""DW01 procurement preparation schema (cases, documents, versioned artifacts).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-24

Lives in the ``tender`` schema (same bounded context). One typed, versioned
artifact store keeps the slice production-shaped without a table per artifact.
All tables are tenant-scoped with FORCE RLS.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

RLS_TABLES = ("preparation_cases", "preparation_documents", "preparation_artifacts")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS tender")

    op.create_table(
        "preparation_cases",
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
        sa.Column("method_key", sa.Text, nullable=True),
        sa.Column("state", sa.Text, nullable=False, server_default="draft"),
        sa.Column("current_step", sa.Text, nullable=False, server_default="intake"),
        sa.Column("last_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("current_official_artifact_id", UUID(as_uuid=True), nullable=True),
        sa.Column("export_ref", sa.Text, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        schema="tender",
    )
    op.create_index(
        "ix_preparation_cases_scope",
        "preparation_cases",
        ["tenant_id", "workspace_id"],
        schema="tender",
    )

    op.create_table(
        "preparation_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "case_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tender.preparation_cases.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        schema="tender",
    )
    op.create_index(
        "ix_preparation_documents_case",
        "preparation_documents",
        ["tenant_id", "workspace_id", "case_id"],
        schema="tender",
    )

    op.create_table(
        "preparation_artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "case_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tender.preparation_cases.id"),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.Text, nullable=False),
        sa.Column("schema_version", sa.Text, nullable=False, server_default="1.0"),
        sa.Column("artifact_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("content_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "source_artifact_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("content_hash", sa.Text, nullable=False, server_default=""),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "case_id", "artifact_type", "artifact_version", name="uq_preparation_artifact_version"
        ),
        schema="tender",
    )
    op.create_index(
        "ix_preparation_artifacts_case",
        "preparation_artifacts",
        ["tenant_id", "workspace_id", "case_id"],
        schema="tender",
    )

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE tender.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE tender.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON tender.{table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dw_app') THEN
                GRANT USAGE ON SCHEMA tender TO dw_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON tender.preparation_cases TO dw_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON tender.preparation_documents TO dw_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON tender.preparation_artifacts TO dw_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"DROP TABLE IF EXISTS tender.{table} CASCADE")
