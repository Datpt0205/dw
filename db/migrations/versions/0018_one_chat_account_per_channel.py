"""One person holds one chat account per channel.

``(issuer, subject)`` was already unique, so a Zalo account belongs to exactly
one person. The other direction was open, and that is the direction that hurts:
somebody changes phone, links the new one, and the old handset keeps speaking
as them forever. It also made two rows where the settings page and the unlink
button each expect one, so both failed for precisely the person who had the
problem.

Scoped to ``provider = 'chat'``. SSO identities are not this feature's to
constrain, and a partial index says so rather than quietly widening the rule.

Existing duplicates are resolved the same way the code now does it: newest
wins, because the newest link is the one the person made on purpose.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

_INDEX = "uq_external_identities_one_chat_per_channel"


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM platform.external_identities e
        USING platform.external_identities newer
        WHERE e.provider = 'chat'
          AND newer.provider = 'chat'
          AND newer.user_id = e.user_id
          AND newer.issuer = e.issuer
          AND (newer.created_at, newer.id) > (e.created_at, e.id)
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX {_INDEX} "
        "ON platform.external_identities (user_id, issuer) WHERE provider = 'chat'"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX platform.{_INDEX}")
