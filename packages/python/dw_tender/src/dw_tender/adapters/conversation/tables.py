"""Table metadata for chat conversations (DDL owned by Alembic 0013)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(schema="tender")

chat_conversations = sa.Table(
    "chat_conversations",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    # e.g. "slack:D0ABC123" (DM) or "slack:C0ABC:1722400000.123" (thread).
    sa.Column("channel_key", sa.Text, nullable=False),
    sa.Column("subject", sa.Text, nullable=False),
    sa.Column("state", sa.Text, nullable=False, server_default="collecting"),
    sa.Column("slots", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("case_id", UUID(as_uuid=True), nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

# Channel-plane dedupe for at-least-once event delivery (Slack retries,
# socket-mode redeliveries). Lives in the platform schema because events arrive
# *before* tenant resolution — same identity-plane rationale as
# ``platform.external_identities`` (no RLS; content is only an opaque event id).
dedupe_metadata = sa.MetaData(schema="platform")

channel_event_dedupe = sa.Table(
    "channel_event_dedupe",
    dedupe_metadata,
    sa.Column("event_id", sa.Text, primary_key=True),
    sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
)
