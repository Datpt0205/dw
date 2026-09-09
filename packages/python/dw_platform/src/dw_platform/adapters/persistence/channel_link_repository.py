"""SQL side of the chat-account link.

Its own session, not the tenant unit of work: every query here runs before any
tenant is known. A chat message arrives with a Zalo id and nothing else, and
the row that says which tenant that id belongs to is precisely what is being
looked up.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError
from dw_platform.adapters.persistence import tables
from dw_platform.application.channel_link import LinkedIdentity
from dw_platform.domain.channel_link import ChannelLinkCode


def _from_row(row: sa.Row[Any]) -> ChannelLinkCode:
    return ChannelLinkCode(
        id=row.id,
        code_hash=row.code_hash,
        user_id=row.user_id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        issuer=row.issuer,
        expires_at=row.expires_at,
        created_at=row.created_at,
        redeemed_at=row.redeemed_at,
        redeemed_subject=row.redeemed_subject,
    )


@dataclass
class SqlChannelLinkRepository:
    session_factory: async_sessionmaker[AsyncSession]

    async def add(self, code: ChannelLinkCode) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(
                sa.insert(tables.channel_link_codes).values(
                    id=code.id,
                    user_id=code.user_id,
                    tenant_id=code.tenant_id,
                    workspace_id=code.workspace_id,
                    issuer=code.issuer,
                    code_hash=code.code_hash,
                    expires_at=code.expires_at,
                    created_at=code.created_at,
                )
            )

    async def find_live(self, *, code_hash: str, issuer: str) -> ChannelLinkCode | None:
        """Unspent and unexpired. Expiry is filtered in SQL so a stale row can
        never be woken up by a clock difference between here and the caller."""
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    sa.select(tables.channel_link_codes).where(
                        tables.channel_link_codes.c.issuer == issuer,
                        tables.channel_link_codes.c.code_hash == code_hash,
                        tables.channel_link_codes.c.redeemed_at.is_(None),
                        tables.channel_link_codes.c.expires_at > datetime.now(tz=UTC),
                    )
                )
            ).first()
        return _from_row(row) if row is not None else None

    async def save(self, code: ChannelLinkCode) -> None:
        """Spend it, and only if it is still unspent.

        The ``redeemed_at IS NULL`` guard is the real single-use lock: two
        messages quoting the same code at once would both pass the read above,
        and exactly one may win here.
        """
        async with self.session_factory() as session, session.begin():
            result = await session.execute(
                sa.update(tables.channel_link_codes)
                .where(
                    tables.channel_link_codes.c.id == code.id,
                    tables.channel_link_codes.c.redeemed_at.is_(None),
                )
                .values(redeemed_at=code.redeemed_at, redeemed_subject=code.redeemed_subject)
            )
            assert isinstance(result, sa.CursorResult)
            if result.rowcount != 1:
                # Two messages raced for one code; this is the one that lost.
                raise ConflictError("mã này đã được dùng rồi")

    async def bound_user(self, *, issuer: str, subject: str) -> UUID | None:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    sa.select(tables.external_identities.c.user_id).where(
                        tables.external_identities.c.issuer == issuer,
                        tables.external_identities.c.subject == subject,
                    )
                )
            ).scalar_one_or_none()

    async def bind(self, *, user_id: UUID, issuer: str, subject: str) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(
                sa.insert(tables.external_identities).values(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    issuer=issuer,
                    subject=subject,
                    provider="chat",
                )
            )

    async def find_binding(self, *, issuer: str, subject: str) -> LinkedIdentity | None:
        """The most recent redemption for this chat account.

        Most recent rather than only: relinking after a phone change writes a
        second row, and the newest one is the live answer.
        """
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    sa.select(
                        tables.channel_link_codes.c.user_id,
                        tables.channel_link_codes.c.tenant_id,
                        tables.channel_link_codes.c.workspace_id,
                    )
                    .where(
                        tables.channel_link_codes.c.issuer == issuer,
                        tables.channel_link_codes.c.redeemed_subject == subject,
                        tables.channel_link_codes.c.redeemed_at.is_not(None),
                    )
                    .order_by(tables.channel_link_codes.c.redeemed_at.desc())
                    .limit(1)
                )
            ).first()
        if row is None:
            return None
        return LinkedIdentity(
            user_id=row.user_id, tenant_id=row.tenant_id, workspace_id=row.workspace_id
        )
