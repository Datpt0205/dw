"""Tell one kind of explanation from another.

``preparation_explanations`` was built for rework support, where the only
question was "why does your work keep coming back". The intake quota asks a
different one — "why do you need another request this period" — but the
lifecycle is identical: someone writes it, someone with authority decides, a
block lifts. Two tables would be two implementations of that lifecycle, and
they would drift.

So one table with a discriminator. The column is not decoration: without it an
approved quota justification would lift a rework block, and vice versa, because
every "has this person been cleared" query looks up by creator and status
alone.

Existing rows are rework by definition — the quota did not exist when they were
written.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "preparation_explanations",
        sa.Column("kind", sa.Text, nullable=False, server_default="rework"),
        schema="tender",
    )
    # Every hot query is "has this person, of this kind, got one in this state".
    op.create_index(
        "ix_preparation_explanations_creator_kind_status",
        "preparation_explanations",
        ["tenant_id", "creator_user_id", "kind", "status"],
        schema="tender",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_preparation_explanations_creator_kind_status",
        table_name="preparation_explanations",
        schema="tender",
    )
    op.drop_column("preparation_explanations", "kind", schema="tender")
