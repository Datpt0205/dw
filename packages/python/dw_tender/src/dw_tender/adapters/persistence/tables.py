"""SQLAlchemy Core tables for the tender schema (mirrors migration 0004)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(schema="tender")

cases = sa.Table(
    "cases",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("last_run_id", UUID(as_uuid=True), nullable=True),
    sa.Column("export_ref", sa.Text, nullable=True),
    sa.Column("created_by", UUID(as_uuid=True), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

documents = sa.Table(
    "documents",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("case_id", UUID(as_uuid=True), nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("supplier_name", sa.Text, nullable=True),
    sa.Column("storage_key", sa.Text, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("knowledge_document_id", UUID(as_uuid=True), nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

requirements = sa.Table(
    "requirements",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("case_id", UUID(as_uuid=True), nullable=False),
    sa.Column("code", sa.Text, nullable=False),
    sa.Column("statement", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("weight", sa.Numeric(6, 4), nullable=False),
)

compliance_findings = sa.Table(
    "compliance_findings",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("case_id", UUID(as_uuid=True), nullable=False),
    sa.Column("requirement_code", sa.Text, nullable=False),
    sa.Column("supplier_name", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("raw_score", sa.Numeric(6, 2), nullable=False),
    sa.Column("note", sa.Text, nullable=False),
    sa.Column("evidence", JSONB, nullable=False),
)

recommendations = sa.Table(
    "recommendations",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("case_id", UUID(as_uuid=True), nullable=False),
    sa.Column("recommended_supplier", sa.Text, nullable=True),
    sa.Column("rationale", sa.Text, nullable=False),
    sa.Column("supplier_scores", JSONB, nullable=False),
    sa.Column("risks", JSONB, nullable=False),
    sa.Column("evidence", JSONB, nullable=False),
    sa.Column("gate_passed", sa.Boolean, nullable=False),
    sa.Column("gate_violations", JSONB, nullable=False),
    sa.Column("scoring_policy_version", sa.Text, nullable=False),
    sa.Column("confidence", sa.Float, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
)
