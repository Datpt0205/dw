"""Issuing a link code, and spending one.

Both halves are here because they are two ends of one exchange, and reading
them apart hides what makes it safe: the identity comes from the web side,
where SSO already established it, and the chat side only ever proves which
account was holding the code.

The binding itself is written to ``platform.external_identities`` — the table
the membership lookup already consults for ``(issuer, subject)``. Nothing new
owns "which platform user is this external account"; this only fills that table
in from a second direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from dw_kernel.errors import ConflictError, NotFoundError
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.domain.channel_link import (
    DEFAULT_TTL,
    ChannelLinkCode,
    fingerprint,
    new_code,
)


class ChannelLinkRepositoryPort(Protocol):
    async def add(self, code: ChannelLinkCode) -> None: ...

    async def find_live(self, *, code_hash: str, issuer: str) -> ChannelLinkCode | None:
        """An unspent, unexpired code with this fingerprint, or nothing."""
        ...

    async def save(self, code: ChannelLinkCode) -> None: ...

    async def bound_user(self, *, issuer: str, subject: str) -> UUID | None:
        """Who this chat account already belongs to, if anyone."""
        ...

    async def bind(self, *, user_id: UUID, issuer: str, subject: str) -> None:
        """Write the identity row the membership lookup reads."""
        ...

    async def find_binding(self, *, issuer: str, subject: str) -> LinkedIdentity | None:
        """Where a linked chat account works.

        Read off the redeemed code rather than ``external_identities``, which
        carries no tenant — a person can belong to several. The redeemed row is
        the record of the context the link was made in, and that is the question
        an incoming chat message actually asks.
        """
        ...


@dataclass(frozen=True)
class IssuedCode:
    code: str
    expires_at: datetime


@dataclass
class IssueChannelLinkCodeHandler:
    """Mint a code for the person who is already signed in.

    No authorization check beyond having a context: the only thing a code can
    do is attach a chat account to *the person who asked for it*. Someone
    minting codes for themselves all day achieves nothing but rows.
    """

    repository: ChannelLinkRepositoryPort
    clock: UtcClock
    id_generator: IdGenerator
    ttl: timedelta = DEFAULT_TTL

    async def handle(self, context: AccessContext, *, issuer: str = "zalo") -> IssuedCode:
        now = self.clock.now().astimezone(UTC)
        code = new_code()
        await self.repository.add(
            ChannelLinkCode(
                id=self.id_generator.new_uuid(),
                code_hash=fingerprint(code),
                user_id=context.principal_id,
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                issuer=issuer,
                expires_at=now + self.ttl,
                created_at=now,
            )
        )
        return IssuedCode(code=code, expires_at=now + self.ttl)


@dataclass(frozen=True)
class LinkedIdentity:
    """Where a redeemed code says this chat account belongs."""

    user_id: UUID
    tenant_id: UUID
    workspace_id: UUID


@dataclass
class RedeemChannelLinkCodeHandler:
    """Spend a code and attach the chat account that quoted it."""

    repository: ChannelLinkRepositoryPort
    clock: UtcClock

    async def handle(self, *, code: str, issuer: str, external_subject: str) -> LinkedIdentity:
        now = self.clock.now().astimezone(UTC)
        record = await self.repository.find_live(code_hash=fingerprint(code), issuer=issuer)
        if record is None or not record.matches(code):
            # One message for wrong, expired and already-spent. Telling them
            # apart would let somebody probe which codes had ever existed.
            raise NotFoundError("mã không đúng hoặc đã hết hạn")

        # Refuse before spending: a chat account already belonging to somebody
        # else is the one case where the code must survive, because its owner
        # did nothing wrong and will need it.
        already = await self.repository.bound_user(issuer=issuer, subject=external_subject)
        if already is not None and already != record.user_id:
            raise ConflictError("tài khoản chat này đã liên kết với người khác")

        record.redeem(external_subject=external_subject, now=now)
        await self.repository.save(record)
        if already is None:
            await self.repository.bind(
                user_id=record.user_id, issuer=issuer, subject=external_subject
            )
        return LinkedIdentity(
            user_id=record.user_id,
            tenant_id=record.tenant_id,
            workspace_id=record.workspace_id,
        )


__all__ = [
    "ChannelLinkRepositoryPort",
    "IssueChannelLinkCodeHandler",
    "IssuedCode",
    "LinkedIdentity",
    "RedeemChannelLinkCodeHandler",
]
