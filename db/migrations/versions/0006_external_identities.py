"""External identity mapping for OIDC (Keycloak) + auto-provisioning.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-24

Adds ``platform.external_identities`` so a verified (issuer, subject) — a
Keycloak ``sub`` or a dev token subject — resolves to a platform user. This is
the identity plane (like ``platform.users``): not tenant-scoped, so no RLS. A
platform user may have several external identities (dev + Keycloak).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_identities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.users.id"),
            nullable=False,
        ),
        sa.Column("issuer", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False, server_default="oidc"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "issuer", "subject", name="uq_external_identities_issuer_subject"
        ),
        schema="platform",
    )
    op.create_index(
        "ix_external_identities_user",
        "external_identities",
        ["user_id"],
        schema="platform",
    )

    # Grant the runtime role DML on the new table (the 0001 blanket grant only
    # covered tables that existed then). Identity plane → no RLS.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dw_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON platform.external_identities TO dw_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_external_identities_user", table_name="external_identities", schema="platform")
    op.drop_table("external_identities", schema="platform")
