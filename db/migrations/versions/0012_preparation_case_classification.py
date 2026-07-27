"""Persist procurement type and business domain on DW01 cases.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


PROCUREMENT_TYPES = (
    "goods",
    "construction",
    "consulting",
    "non_consulting",
    "mixed",
    "investor_selection",
    "other",
)
BUSINESS_DOMAINS = (
    "general",
    "information_technology",
    "real_estate",
    "healthcare",
    "infrastructure",
    "operations",
    "energy",
    "education",
    "other",
)


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


def upgrade() -> None:
    op.add_column(
        "preparation_cases",
        sa.Column(
            "procurement_type",
            sa.Text,
            nullable=False,
            server_default="other",
        ),
        schema="tender",
    )
    op.add_column(
        "preparation_cases",
        sa.Column(
            "business_domain",
            sa.Text,
            nullable=False,
            server_default="general",
        ),
        schema="tender",
    )
    op.create_check_constraint(
        "ck_preparation_case_procurement_type",
        "preparation_cases",
        f"procurement_type IN ({_values(PROCUREMENT_TYPES)})",
        schema="tender",
    )
    op.create_check_constraint(
        "ck_preparation_case_business_domain",
        "preparation_cases",
        f"business_domain IN ({_values(BUSINESS_DOMAINS)})",
        schema="tender",
    )
    op.create_index(
        "ix_preparation_case_classification",
        "preparation_cases",
        ["tenant_id", "workspace_id", "procurement_type", "business_domain"],
        schema="tender",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_preparation_case_classification",
        table_name="preparation_cases",
        schema="tender",
    )
    op.drop_constraint(
        "ck_preparation_case_business_domain",
        "preparation_cases",
        schema="tender",
        type_="check",
    )
    op.drop_constraint(
        "ck_preparation_case_procurement_type",
        "preparation_cases",
        schema="tender",
        type_="check",
    )
    op.drop_column("preparation_cases", "business_domain", schema="tender")
    op.drop_column("preparation_cases", "procurement_type", schema="tender")
