"""Idempotent demo seed: roles, plans, two tenants with users and memberships.

Runs as the migrator role (BYPASSRLS maintenance role) via DW_DATABASE_URL.
Deterministic UUIDs (uuid5) + ON CONFLICT upserts → re-running never creates
duplicates.

Usage: uv run python scripts/seed_demo.py [--database-url URL]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine

from dw_platform.adapters.persistence import tables

SEED_NAMESPACE = uuid.UUID("6f0f6f1e-9f6a-4f65-9a1c-000000000d10")


def sid(kind: str, key: str) -> uuid.UUID:
    """Stable deterministic id for a seed entity."""
    return uuid.uuid5(SEED_NAMESPACE, f"{kind}:{key}")


ROLES = [
    {
        "key": "platform_admin",
        "name": "Platform Administrator",
        "scopes": ["platform.admin"],
    },
    {
        "key": "approver",
        "name": "Approver",
        "scopes": ["approvals.read", "approvals.decide", "work_ops.read", "tender.read"],
    },
    {
        "key": "member",
        "name": "Member",
        "scopes": [
            "work_ops.read",
            "work_ops.write",
            "tender.read",
            "tender.write",
            "approvals.read",
            "knowledge.read",
        ],
    },
]

PLANS = [
    {
        "plan_id": "basic",
        "name": "Basic",
        "features": ["work_ops_worker"],
        "quotas": {"runs_per_day": 20},
    },
    {
        "plan_id": "professional",
        "name": "Professional",
        "features": ["work_ops_worker", "tender_worker", "knowledge_search"],
        "quotas": {"runs_per_day": 200},
    },
    {
        "plan_id": "enterprise",
        "name": "Enterprise",
        "features": [
            "work_ops_worker",
            "tender_worker",
            "knowledge_search",
            "audit_export",
        ],
        "quotas": {"runs_per_day": 2000},
    },
]

TENANTS = [
    {"slug": "tenant-alpha", "name": "Công ty Alpha", "plan_id": "professional"},
    {"slug": "tenant-beta", "name": "Công ty Beta", "plan_id": "basic"},
]

USERS = [
    # (subject, email, display_name, tenant_slug, roles)
    ("dev|an.nguyen", "an.nguyen@alpha.local", "Nguyễn Văn An", "tenant-alpha", ["member"]),
    ("dev|binh.tran", "binh.tran@alpha.local", "Trần Thị Bình", "tenant-alpha", ["approver"]),
    (
        "dev|chi.le",
        "chi.le@alpha.local",
        "Lê Thị Chi",
        "tenant-alpha",
        ["platform_admin", "member"],
    ),
    ("dev|bao.pham", "bao.pham@beta.local", "Phạm Quốc Bảo", "tenant-beta", ["member"]),
    ("dev|dung.vo", "dung.vo@beta.local", "Võ Thị Dung", "tenant-beta", ["approver"]),
]


async def seed(database_url: str) -> dict[str, int]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            for role in ROLES:
                stmt = pg_insert(tables.roles).values(**role)
                await conn.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["key"],
                        set_={"name": stmt.excluded.name, "scopes": stmt.excluded.scopes},
                    )
                )

            for plan in PLANS:
                stmt = pg_insert(tables.plans).values(**plan)
                await conn.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["plan_id"],
                        set_={
                            "name": stmt.excluded.name,
                            "features": stmt.excluded.features,
                            "quotas": stmt.excluded.quotas,
                        },
                    )
                )

            for tenant in TENANTS:
                tenant_id = sid("tenant", tenant["slug"])
                stmt = pg_insert(tables.tenants).values(
                    id=tenant_id, slug=tenant["slug"], name=tenant["name"]
                )
                await conn.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["slug"], set_={"name": stmt.excluded.name}
                    )
                )

                workspace_id = sid("workspace", f"{tenant['slug']}:main")
                ws_stmt = pg_insert(tables.workspaces).values(
                    id=workspace_id, tenant_id=tenant_id, slug="main", name="Main workspace"
                )
                await conn.execute(
                    ws_stmt.on_conflict_do_update(
                        constraint="uq_workspaces_tenant_slug",
                        set_={"name": ws_stmt.excluded.name},
                    )
                )

                ent_stmt = pg_insert(tables.entitlements).values(
                    id=sid("entitlement", tenant["slug"]),
                    tenant_id=tenant_id,
                    plan_id=tenant["plan_id"],
                    feature_overrides=[],
                )
                await conn.execute(
                    ent_stmt.on_conflict_do_update(
                        index_elements=["tenant_id"],
                        set_={"plan_id": ent_stmt.excluded.plan_id},
                    )
                )

            for subject, email, display_name, tenant_slug, role_keys in USERS:
                user_id = sid("user", subject)
                user_stmt = pg_insert(tables.users).values(
                    id=user_id, subject=subject, email=email, display_name=display_name
                )
                await conn.execute(
                    user_stmt.on_conflict_do_update(
                        index_elements=["subject"],
                        set_={
                            "email": user_stmt.excluded.email,
                            "display_name": user_stmt.excluded.display_name,
                        },
                    )
                )

                membership_stmt = pg_insert(tables.memberships).values(
                    id=sid("membership", f"{tenant_slug}:{subject}"),
                    tenant_id=sid("tenant", tenant_slug),
                    workspace_id=sid("workspace", f"{tenant_slug}:main"),
                    user_id=user_id,
                    role_keys=role_keys,
                )
                await conn.execute(
                    membership_stmt.on_conflict_do_update(
                        constraint="uq_memberships_scope_user",
                        set_={"role_keys": membership_stmt.excluded.role_keys},
                    )
                )

        async with engine.connect() as conn:
            counts: dict[str, int] = {}
            for name, table in {
                "tenants": tables.tenants,
                "workspaces": tables.workspaces,
                "users": tables.users,
                "roles": tables.roles,
                "plans": tables.plans,
                "memberships": tables.memberships,
                "entitlements": tables.entitlements,
            }.items():
                counts[name] = (
                    await conn.execute(sa.select(sa.func.count()).select_from(table))
                ).scalar_one()
        return counts
    finally:
        await engine.dispose()


def main() -> int:
    # Windows consoles default to cp1252; demo data is Vietnamese.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DW_DATABASE_URL"),
        help="SQLAlchemy async URL (defaults to DW_DATABASE_URL)",
    )
    args = parser.parse_args()
    if not args.database_url:
        print("ERROR: provide --database-url or set DW_DATABASE_URL", file=sys.stderr)
        return 2

    counts = asyncio.run(seed(args.database_url))
    print("Seed complete (idempotent). Row counts:")
    for name, count in counts.items():
        print(f"  {name:14s} {count}")
    print("\nDemo identities (issue tokens with scripts/issue_dev_token.py):")
    for subject, _email, display_name, tenant_slug, roles in USERS:
        print(f"  {subject:18s} {display_name:18s} {tenant_slug:14s} roles={','.join(roles)}")
    print(f"\n  tenant-alpha id: {sid('tenant', 'tenant-alpha')}")
    print(f"  tenant-alpha workspace: {sid('workspace', 'tenant-alpha:main')}")
    print(f"  tenant-beta id: {sid('tenant', 'tenant-beta')}")
    print(f"  tenant-beta workspace: {sid('workspace', 'tenant-beta:main')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
