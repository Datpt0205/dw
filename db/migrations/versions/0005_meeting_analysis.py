"""Meeting quality analysis (phase 7B): work_ops.meetings.analysis JSONB.

RLS is inherited from the existing table policy — no new grants needed.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meetings",
        sa.Column("analysis", JSONB, nullable=True),
        schema="work_ops",
    )


def downgrade() -> None:
    op.drop_column("meetings", "analysis", schema="work_ops")
