"""SQLAlchemy Core tables for the knowledge schema (mirrors migration 0002)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(schema="knowledge")

documents = sa.Table(
    "documents",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("domain", sa.Text, nullable=False),
    sa.Column("source_uri", sa.Text, nullable=False),
    sa.Column("classification", sa.Text, nullable=False),
    sa.Column("source_version", sa.Text, nullable=False),
    sa.Column("index_version", sa.Text, nullable=True),
    sa.Column("created_by", UUID(as_uuid=True), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

chunks = sa.Table(
    "chunks",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("document_id", UUID(as_uuid=True), nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("start_offset", sa.Integer, nullable=False),
    sa.Column("end_offset", sa.Integer, nullable=False),
    sa.Column("provenance_hash", sa.Text, nullable=False),
    sa.Column("metadata", JSONB, nullable=False),
)
