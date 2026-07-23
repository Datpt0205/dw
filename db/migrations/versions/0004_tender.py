"""Tender schema (blueprint §19.3).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-23

Deferred (documented): tender.criteria (kind+weight live on requirements),
tender.suppliers/submissions (supplier name + kind live on documents),
tender.evidence_links (evidence stored as JSONB refs on findings and
recommendations) — normalized out when reporting needs demand it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

RLS_TABLES = ("cases", "documents", "requirements", "compliance_findings", "recommendations")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS tender")

    op.create_table(
        "cases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default="created"),
        sa.Column("last_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("export_ref", sa.Text, nullable=True),
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
        schema="tender",
    )

    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "case_id", UUID(as_uuid=True), sa.ForeignKey("tender.cases.id"), nullable=False
        ),
        sa.Column("kind", sa.Text, nullable=False),  # rfq | supplier_submission | other
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("supplier_name", sa.Text, nullable=True),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("knowledge_document_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="tender",
    )

    op.create_table(
        "requirements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "case_id", UUID(as_uuid=True), sa.ForeignKey("tender.cases.id"), nullable=False
        ),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("statement", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),  # mandatory | weighted | informational
        sa.Column("weight", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.UniqueConstraint("case_id", "code", name="uq_requirements_case_code"),
        schema="tender",
    )

    op.create_table(
        "compliance_findings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "case_id", UUID(as_uuid=True), sa.ForeignKey("tender.cases.id"), nullable=False
        ),
        sa.Column("requirement_code", sa.Text, nullable=False),
        sa.Column("supplier_name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("raw_score", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.UniqueConstraint(
            "case_id", "requirement_code", "supplier_name", name="uq_findings_case_req_supplier"
        ),
        schema="tender",
    )

    op.create_table(
        "recommendations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "case_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tender.cases.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("recommended_supplier", sa.Text, nullable=True),
        sa.Column("rationale", sa.Text, nullable=False, server_default=""),
        sa.Column("supplier_scores", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("risks", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("gate_passed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "gate_violations", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("scoring_policy_version", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
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
                    ON ALL TABLES IN SCHEMA tender TO dw_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA tender CASCADE")
