"""Manual-upload intake verification and source-file metadata for DW01.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "preparation_cases",
        sa.Column("intake_verified_by", UUID(as_uuid=True), nullable=True),
        schema="tender",
    )
    op.add_column(
        "preparation_cases",
        sa.Column("intake_verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        schema="tender",
    )
    op.add_column(
        "preparation_documents",
        sa.Column("filename", sa.Text, nullable=False, server_default="source.txt"),
        schema="tender",
    )
    op.add_column(
        "preparation_documents",
        sa.Column(
            "content_type",
            sa.Text,
            nullable=False,
            server_default="text/plain; charset=utf-8",
        ),
        schema="tender",
    )
    op.add_column(
        "preparation_documents",
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        schema="tender",
    )


def downgrade() -> None:
    op.drop_column("preparation_documents", "size_bytes", schema="tender")
    op.drop_column("preparation_documents", "content_type", schema="tender")
    op.drop_column("preparation_documents", "filename", schema="tender")
    op.drop_column("preparation_cases", "intake_verified_at", schema="tender")
    op.drop_column("preparation_cases", "intake_verified_by", schema="tender")
