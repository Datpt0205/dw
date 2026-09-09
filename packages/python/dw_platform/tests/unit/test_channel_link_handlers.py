"""Issuing, redeeming, unlinking — the exchange as a whole.

The fake repository below keeps the two rules the database keeps, and for the
same reasons. ``(issuer, subject)`` unique means a chat account belongs to one
person. ``(user_id, issuer)`` unique among chat rows means a person holds one
chat account per channel — the direction that was left open, and the one that
hurt: a replaced phone kept speaking as its owner, and the settings page and
the unlink button each found two answers where they expect one.

A fake more permissive than the database is a fake that passes while production
fails, so both rules are enforced here rather than assumed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from dw_kernel.errors import ConflictError, NotFoundError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.channel_link import (
    DescribeChannelLinksHandler,
    IssueChannelLinkCodeHandler,
    LinkedIdentity,
    RedeemChannelLinkCodeHandler,
    UnlinkChannelHandler,
)
from dw_platform.domain.channel_link import ChannelLinkCode

NOW = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.moment = now

    def now(self) -> datetime:
        return self.moment


class _Ids:
    def new_uuid(self) -> uuid.UUID:
        return uuid.uuid4()


class FakeRepository:
    """In-memory, with the database's uniqueness rules kept honestly.

    It reads the same clock the handlers do, because the real repository
    filters expiry in SQL: an expired code is simply not found there, and a
    fake that returned it would test a path production cannot reach.
    """

    def __init__(self, clock: _Clock | None = None) -> None:
        self.clock = clock or _Clock()
        self.codes: dict[uuid.UUID, ChannelLinkCode] = {}
        self.bindings: dict[tuple[str, str], uuid.UUID] = {}

    async def add(self, code: ChannelLinkCode) -> None:
        self.codes[code.id] = code

    async def find_live(self, *, code_hash: str, issuer: str) -> ChannelLinkCode | None:
        return next(
            (
                code
                for code in self.codes.values()
                if code.issuer == issuer
                and code.code_hash == code_hash
                and not code.spent
                and code.expires_at > self.clock.now()
            ),
            None,
        )

    async def save(self, code: ChannelLinkCode) -> None:
        self.codes[code.id] = code

    async def bound_user(self, *, issuer: str, subject: str) -> uuid.UUID | None:
        return self.bindings.get((issuer, subject))

    async def bind(self, *, user_id: uuid.UUID, issuer: str, subject: str) -> None:
        for channel, account in list(self.bindings):
            if self.bindings[channel, account] == user_id and channel == issuer:
                del self.bindings[channel, account]
        self.bindings[issuer, subject] = user_id

    async def unbind(self, *, user_id: uuid.UUID, issuer: str) -> str:
        for channel, account in list(self.bindings):
            if self.bindings[channel, account] == user_id and channel == issuer:
                del self.bindings[channel, account]
                return account
        return ""

    async def linked_subject(self, *, user_id: uuid.UUID, issuer: str) -> str | None:
        found = [
            account
            for (channel, account), owner in self.bindings.items()
            if owner == user_id and channel == issuer
        ]
        assert len(found) <= 1, "one person, one chat account per channel"
        return found[0] if found else None

    async def find_binding(self, *, issuer: str, subject: str) -> LinkedIdentity | None:
        owner = self.bindings.get((issuer, subject))
        if owner is None:
            return None
        return LinkedIdentity(user_id=owner, tenant_id=TENANT, workspace_id=WORKSPACE)


def _context(principal: uuid.UUID) -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_id=principal,
        roles=frozenset({"member"}),
        plan_id="pro",
    )


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


def _handlers(
    repository: FakeRepository, *, clock: _Clock | None = None
) -> tuple[
    IssueChannelLinkCodeHandler,
    RedeemChannelLinkCodeHandler,
    UnlinkChannelHandler,
    DescribeChannelLinksHandler,
]:
    tick = clock or _Clock()
    repository.clock = tick
    return (
        IssueChannelLinkCodeHandler(repository=repository, clock=tick, id_generator=_Ids()),
        RedeemChannelLinkCodeHandler(repository=repository, clock=tick),
        UnlinkChannelHandler(repository=repository),
        DescribeChannelLinksHandler(repository=repository),
    )


# ------------------------------------------------------------- the happy path --
@pytest.mark.asyncio
async def test_a_redeemed_code_makes_the_chat_account_resolve_to_its_owner(
    repository: FakeRepository,
) -> None:
    an = uuid.uuid4()
    issue, redeem, _, _ = _handlers(repository)

    issued = await issue.handle(_context(an))
    linked = await redeem.handle(code=issued.code, issuer="zalo", external_subject="zalo-an")

    assert linked.user_id == an
    binding = await repository.find_binding(issuer="zalo", subject="zalo-an")
    assert binding is not None
    assert binding.user_id == an


@pytest.mark.asyncio
async def test_the_code_decides_the_person_not_the_account_that_types_it(
    repository: FakeRepository,
) -> None:
    an = uuid.uuid4()
    issue, redeem, _, _ = _handlers(repository)

    issued = await issue.handle(_context(an))
    linked = await redeem.handle(code=issued.code, issuer="zalo", external_subject="zalo-chi")

    assert linked.user_id == an


# ---------------------------------------------------- one account per channel --
@pytest.mark.asyncio
async def test_a_new_phone_replaces_the_old_one(repository: FakeRepository) -> None:
    """The defect this suite was written for: the old handset must go quiet."""
    an = uuid.uuid4()
    issue, redeem, _, describe = _handlers(repository)

    first = await issue.handle(_context(an))
    await redeem.handle(code=first.code, issuer="zalo", external_subject="zalo-old-phone")
    second = await issue.handle(_context(an))
    await redeem.handle(code=second.code, issuer="zalo", external_subject="zalo-new-phone")

    assert await repository.find_binding(issuer="zalo", subject="zalo-old-phone") is None
    assert await repository.find_binding(issuer="zalo", subject="zalo-new-phone") is not None
    assert await describe.handle(_context(an)) == {"zalo": "zalo-new-phone"}


@pytest.mark.asyncio
async def test_relinking_the_same_account_is_harmless(repository: FakeRepository) -> None:
    an = uuid.uuid4()
    issue, redeem, _, describe = _handlers(repository)

    first = await issue.handle(_context(an))
    await redeem.handle(code=first.code, issuer="zalo", external_subject="zalo-an")
    second = await issue.handle(_context(an))
    await redeem.handle(code=second.code, issuer="zalo", external_subject="zalo-an")

    assert await describe.handle(_context(an)) == {"zalo": "zalo-an"}


@pytest.mark.asyncio
async def test_a_chat_account_belonging_to_someone_else_is_refused(
    repository: FakeRepository,
) -> None:
    an = uuid.uuid4()
    chi = uuid.uuid4()
    issue, redeem, _, _ = _handlers(repository)

    hers = await issue.handle(_context(chi))
    await redeem.handle(code=hers.code, issuer="zalo", external_subject="zalo-chi")

    his = await issue.handle(_context(an))
    with pytest.raises(ConflictError):
        await redeem.handle(code=his.code, issuer="zalo", external_subject="zalo-chi")

    binding = await repository.find_binding(issuer="zalo", subject="zalo-chi")
    assert binding is not None
    assert binding.user_id == chi, "she keeps her account"


@pytest.mark.asyncio
async def test_the_refused_code_survives_for_its_own_owner(repository: FakeRepository) -> None:
    """He did nothing wrong, so his code must still work on his own account."""
    an = uuid.uuid4()
    chi = uuid.uuid4()
    issue, redeem, _, _ = _handlers(repository)

    hers = await issue.handle(_context(chi))
    await redeem.handle(code=hers.code, issuer="zalo", external_subject="zalo-chi")

    his = await issue.handle(_context(an))
    with pytest.raises(ConflictError):
        await redeem.handle(code=his.code, issuer="zalo", external_subject="zalo-chi")

    linked = await redeem.handle(code=his.code, issuer="zalo", external_subject="zalo-an")
    assert linked.user_id == an


# ---------------------------------------------------------------- single use --
@pytest.mark.asyncio
async def test_a_spent_code_cannot_be_used_by_a_second_account(
    repository: FakeRepository,
) -> None:
    an = uuid.uuid4()
    issue, redeem, _, _ = _handlers(repository)

    issued = await issue.handle(_context(an))
    await redeem.handle(code=issued.code, issuer="zalo", external_subject="zalo-an")
    with pytest.raises((NotFoundError, ConflictError)):
        await redeem.handle(code=issued.code, issuer="zalo", external_subject="zalo-other")


@pytest.mark.asyncio
async def test_an_expired_code_is_indistinguishable_from_a_wrong_one(
    repository: FakeRepository,
) -> None:
    """Same message either way, so nobody can probe which codes ever existed."""
    an = uuid.uuid4()
    clock = _Clock()
    issue, redeem, _, _ = _handlers(repository, clock=clock)
    issue.ttl = timedelta(minutes=10)

    issued = await issue.handle(_context(an))
    clock.moment = NOW + timedelta(minutes=11)

    with pytest.raises(NotFoundError) as expired:
        await redeem.handle(code=issued.code, issuer="zalo", external_subject="zalo-an")
    with pytest.raises(NotFoundError) as nonsense:
        await redeem.handle(code="ZZZZZZZZ", issuer="zalo", external_subject="zalo-an")
    assert str(expired.value) == str(nonsense.value)


# ----------------------------------------------------------------- unlinking --
@pytest.mark.asyncio
async def test_unlinking_stops_the_chat_account_resolving(repository: FakeRepository) -> None:
    an = uuid.uuid4()
    issue, redeem, unlink, describe = _handlers(repository)

    issued = await issue.handle(_context(an))
    await redeem.handle(code=issued.code, issuer="zalo", external_subject="zalo-an")

    assert await unlink.handle(_context(an)) == "zalo-an"
    assert await repository.find_binding(issuer="zalo", subject="zalo-an") is None
    assert await describe.handle(_context(an)) == {"zalo": None}


@pytest.mark.asyncio
async def test_unlinking_nothing_is_harmless(repository: FakeRepository) -> None:
    _, _, unlink, _ = _handlers(repository)
    assert await unlink.handle(_context(uuid.uuid4())) == ""


@pytest.mark.asyncio
async def test_unlinking_touches_only_your_own_account(repository: FakeRepository) -> None:
    """Scoped by the caller's identity, so quoting a Zalo id disconnects nobody."""
    an = uuid.uuid4()
    chi = uuid.uuid4()
    issue, redeem, unlink, _ = _handlers(repository)

    for person, account in ((an, "zalo-an"), (chi, "zalo-chi")):
        issued = await issue.handle(_context(person))
        await redeem.handle(code=issued.code, issuer="zalo", external_subject=account)

    await unlink.handle(_context(an))
    assert await repository.find_binding(issuer="zalo", subject="zalo-chi") is not None


@pytest.mark.asyncio
async def test_you_can_link_again_after_unlinking(repository: FakeRepository) -> None:
    an = uuid.uuid4()
    issue, redeem, unlink, describe = _handlers(repository)

    first = await issue.handle(_context(an))
    await redeem.handle(code=first.code, issuer="zalo", external_subject="zalo-an")
    await unlink.handle(_context(an))

    second = await issue.handle(_context(an))
    await redeem.handle(code=second.code, issuer="zalo", external_subject="zalo-an")
    assert await describe.handle(_context(an)) == {"zalo": "zalo-an"}
