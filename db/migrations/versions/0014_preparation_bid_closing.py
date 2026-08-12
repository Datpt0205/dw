"""Persist the bid-closing moment on DW01 cases.

Opening bids is driven by a deadline, not by a headcount: at the closing time
the inviting party opens whatever arrived. Until now the case only carried a
free-text ``deadline`` ("90 ngày") that nothing compared against a clock, so a
package short of suppliers sat in receiving_bids indefinitely.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "preparation_cases",
        sa.Column("bids_close_at", sa.DateTime(timezone=True), nullable=True),
        schema="tender",
    )
    # The scanner asks one question: which open cases are past their closing
    # moment? Partial index keeps it cheap as completed cases pile up.
    op.create_index(
        "ix_preparation_cases_bids_close_at",
        "preparation_cases",
        ["bids_close_at"],
        schema="tender",
        postgresql_where=sa.text("bids_close_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_preparation_cases_bids_close_at", table_name="preparation_cases", schema="tender"
    )
    op.drop_column("preparation_cases", "bids_close_at", schema="tender")
