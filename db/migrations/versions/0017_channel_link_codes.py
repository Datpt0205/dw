"""One-time codes that tie a chat account to a corporate identity.

Replaces a hand-maintained file mapping Zalo user ids to people — workable for
a demo, wrong from the first day somebody joins or leaves.

The row outlives its redemption on purpose. ``external_identities`` answers
"which platform user is this chat account" but carries no tenant, and a person
can belong to several; the redeemed row is the record of which tenant and
workspace the link was made in, which is what an arriving chat message needs.

Only the hash is stored. A dump then hands nobody a live code.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_link_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The context the code was minted in — carried through redemption so an
        # incoming message knows where its sender works.
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("issuer", sa.Text, nullable=False),
        sa.Column("code_hash", sa.Text, nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("redeemed_subject", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "(redeemed_at IS NULL) = (redeemed_subject = '')",
            name="ck_channel_link_redemption_complete",
        ),
        schema="platform",
    )
    # Redemption looks a code up by its fingerprint within one channel.
    op.create_index(
        "uq_channel_link_codes_hash",
        "channel_link_codes",
        ["issuer", "code_hash"],
        unique=True,
        schema="platform",
    )
    # And every arriving message asks "where does this chat account work".
    op.create_index(
        "ix_channel_link_codes_subject",
        "channel_link_codes",
        ["issuer", "redeemed_subject"],
        schema="platform",
        postgresql_where=sa.text("redeemed_at IS NOT NULL"),
    )

    # Column-level grants, same discipline as the rework tables: no DELETE, and
    # UPDATE only on the two columns a redemption touches. Everything above
    # them is written once and must stay as issued — an editable ``user_id``
    # would turn a spent code into a way to point somebody else's chat account
    # at a different person.
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dw_app') THEN
            GRANT SELECT, INSERT ON platform.channel_link_codes TO dw_app;
            GRANT UPDATE (redeemed_at, redeemed_subject)
              ON platform.channel_link_codes TO dw_app;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_link_codes_subject", table_name="channel_link_codes", schema="platform"
    )
    op.drop_index("uq_channel_link_codes_hash", table_name="channel_link_codes", schema="platform")
    op.drop_table("channel_link_codes", schema="platform")
