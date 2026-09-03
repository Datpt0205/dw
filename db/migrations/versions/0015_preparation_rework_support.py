"""Returned DW01 cases, and the written context that unblocks their author.

Until now a returned case left no trace anyone could count: intake rejections
wrote a single audit line, CP1/CP2 rejections wrote none at all, and the
progress card telling the requester what to fix scrolled away. So a person
being handed the same correction for the fourth time in a fortnight was
visible to nobody — not to them, not to procurement.

Two tables, both append-only, because a tally that can stop someone from
working must rest on records the application layer cannot quietly rewrite.
That is enforced here rather than by convention: no DELETE is granted, and
UPDATE is granted per column — the three void columns on one table, the four
decision columns on the other. An attempt to edit a stored reason fails in the
database instead of getting past a code review.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_TABLES = ("preparation_rework_events", "preparation_explanations")


def upgrade() -> None:
    op.create_table(
        "preparation_rework_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "case_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tender.preparation_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Whose case it was — the key the tally groups by. Not the person who
        # clicked submit: filing on a colleague's behalf must never land on
        # the wrong tally.
        sa.Column("creator_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("decided_by_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint", sa.Text, nullable=False),
        sa.Column("reason_code", sa.Text, nullable=False),
        sa.Column("reason_text", sa.Text, nullable=False),
        # Which thresholds were in force. A blocking decision made months ago
        # has to be traceable to the rule pack that produced it.
        sa.Column("policy_version", sa.Text, nullable=False, server_default=""),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # A mis-click, marked as such. The row survives for the audit trail;
        # the count moves on without it.
        sa.Column("voided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("voided_by", UUID(as_uuid=True), nullable=True),
        sa.Column("void_reason", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "checkpoint IN ('intake','cp1','cp2')",
            name="ck_prep_rework_checkpoint",
        ),
        sa.CheckConstraint(
            "btrim(reason_text) <> ''",
            name="ck_prep_rework_reason_text",
        ),
        schema="tender",
    )
    # The one query the whole feature runs: this person's returns since a
    # moment. Mirrors ix_audit_events_tenant_time in shape and in purpose.
    op.create_index(
        "ix_prep_rework_creator_time",
        "preparation_rework_events",
        ["tenant_id", "workspace_id", "creator_user_id", "occurred_at"],
        schema="tender",
    )
    op.create_index(
        "ix_prep_rework_case",
        "preparation_rework_events",
        ["tenant_id", "case_id", "occurred_at"],
        schema="tender",
    )

    op.create_table(
        "preparation_explanations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        # Nullable: a person is blocked, not a case. The explanation is often
        # written from a case page and worth linking, but it is not owned by
        # one — and the case it was written from may be closed later.
        sa.Column(
            "case_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tender.preparation_cases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("creator_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("context_text", sa.Text, nullable=False),
        sa.Column("difficulty_text", sa.Text, nullable=False, server_default=""),
        sa.Column("support_request_text", sa.Text, nullable=False, server_default=""),
        # What had pushed this person over at the moment they wrote it. Frozen
        # here because the window keeps moving: reopened weeks later, the live
        # tally would make the explanation look like an answer to a different
        # set of facts than the one it was written about.
        sa.Column(
            "counted_event_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("nudge_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("block_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("top_reason_code", sa.Text, nullable=False, server_default=""),
        sa.Column("policy_version", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("decided_by", UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("decision_comment", sa.Text, nullable=False, server_default=""),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_prep_explanation_status",
        ),
        sa.CheckConstraint(
            "btrim(context_text) <> ''",
            name="ck_prep_explanation_context",
        ),
        # A decision is attributable or it is not a decision.
        sa.CheckConstraint(
            "status = 'pending' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL"
            " AND btrim(decision_comment) <> '')",
            name="ck_prep_explanation_decision_complete",
        ),
        schema="tender",
    )
    op.create_index(
        "ix_prep_explanation_creator",
        "preparation_explanations",
        ["tenant_id", "workspace_id", "creator_user_id", "submitted_at"],
        schema="tender",
    )
    # The escalation scanner asks one question: what is still waiting? Partial
    # index keeps it cheap as decided rows accumulate.
    op.create_index(
        "ix_prep_explanation_pending",
        "preparation_explanations",
        ["submitted_at"],
        schema="tender",
        postgresql_where=sa.text("status = 'pending'"),
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE tender.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE tender.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table}
            ON tender.{table}
            USING (
              tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            WITH CHECK (
              tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            """
        )

    # Column-level grants: the immutability rule, enforced by the database
    # rather than by everyone remembering it. No DELETE anywhere; UPDATE only
    # on the columns a legitimate correction or decision touches.
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'dw_app') THEN
            GRANT SELECT, INSERT ON tender.preparation_rework_events TO dw_app;
            GRANT UPDATE (voided_at, voided_by, void_reason)
              ON tender.preparation_rework_events TO dw_app;
            GRANT SELECT, INSERT ON tender.preparation_explanations TO dw_app;
            GRANT UPDATE (status, decided_by, decided_at, decision_comment)
              ON tender.preparation_explanations TO dw_app;
          END IF;
        END $$;
        """
    )

    # The escalation worker reads pending explanations under the same narrowly
    # scoped GUC the notification drain already uses. It cannot mutate them.
    op.execute(
        """
        CREATE POLICY worker_read_preparation_explanations
        ON tender.preparation_explanations
        FOR SELECT
        USING (current_setting('app.worker_drain', true) = 'on')
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS worker_read_preparation_explanations "
        "ON tender.preparation_explanations"
    )
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON tender.{table}")
    op.drop_index(
        "ix_prep_explanation_pending", table_name="preparation_explanations", schema="tender"
    )
    op.drop_index(
        "ix_prep_explanation_creator", table_name="preparation_explanations", schema="tender"
    )
    op.drop_table("preparation_explanations", schema="tender")
    op.drop_index("ix_prep_rework_case", table_name="preparation_rework_events", schema="tender")
    op.drop_index(
        "ix_prep_rework_creator_time", table_name="preparation_rework_events", schema="tender"
    )
    op.drop_table("preparation_rework_events", schema="tender")
