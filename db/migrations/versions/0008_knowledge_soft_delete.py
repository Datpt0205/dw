"""Soft-delete + versioning for the knowledge plane (B0).

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-25

Documents/chunks are never hard-deleted on update or user delete: they are
tombstoned (``status``) or superseded (``is_current`` + effective dating), kept
for legal traceability, and only purged after a retention window by a worker job.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- documents: versioning + soft-delete -------------------------------
    op.add_column(
        "documents",
        sa.Column("doc_key", UUID(as_uuid=True), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "documents",
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        schema="knowledge",
    )
    op.add_column(
        "documents",
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.text("true")),
        schema="knowledge",
    )
    op.add_column(
        "documents",
        sa.Column("effective_from", sa.TIMESTAMP(timezone=True), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "documents",
        sa.Column("effective_to", sa.TIMESTAMP(timezone=True), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "documents",
        sa.Column("superseded_by", UUID(as_uuid=True), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "documents",
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "documents",
        sa.Column("deleted_by", UUID(as_uuid=True), nullable=True),
        schema="knowledge",
    )
    op.create_index(
        "ix_documents_doc_key_current",
        "documents",
        ["doc_key", "is_current"],
        schema="knowledge",
    )
    op.create_index(
        "ix_documents_status",
        "documents",
        ["tenant_id", "status"],
        schema="knowledge",
    )

    # --- chunks: soft-delete ----------------------------------------------
    op.add_column(
        "chunks",
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        schema="knowledge",
    )
    op.add_column(
        "chunks",
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        schema="knowledge",
    )
    op.create_index(
        "ix_chunks_document_status",
        "chunks",
        ["document_id", "status"],
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_document_status", table_name="chunks", schema="knowledge")
    op.drop_column("chunks", "deleted_at", schema="knowledge")
    op.drop_column("chunks", "status", schema="knowledge")
    op.drop_index("ix_documents_status", table_name="documents", schema="knowledge")
    op.drop_index("ix_documents_doc_key_current", table_name="documents", schema="knowledge")
    for col in (
        "deleted_by",
        "deleted_at",
        "superseded_by",
        "effective_to",
        "effective_from",
        "is_current",
        "status",
        "doc_key",
    ):
        op.drop_column("documents", col, schema="knowledge")
