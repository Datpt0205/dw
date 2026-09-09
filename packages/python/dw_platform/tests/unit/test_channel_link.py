"""The rules a link code lives by.

Three properties do the security work and each has a test that fails loudly if
it is weakened: short-lived, single-use, and never stored in the clear.

The fourth is about people rather than attackers. The code is read off a screen
and typed into a phone, so transcription has to be forgiving — case, spaces and
dashes are noise somebody adds, not a different code.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from dw_kernel.errors import ConflictError, DomainError
from dw_platform.domain.channel_link import (
    ChannelLinkCode,
    fingerprint,
    looks_like_a_code,
    new_code,
    normalise,
)

NOW = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)


def _code(
    *, expires_in: timedelta = timedelta(minutes=10), plain: str = "ABCD2345"
) -> ChannelLinkCode:
    return ChannelLinkCode(
        id=uuid.uuid4(),
        code_hash=fingerprint(plain),
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        issuer="zalo",
        expires_at=NOW + expires_in,
        created_at=NOW,
    )


# ------------------------------------------------------------ what is stored --
def test_the_code_itself_is_never_the_thing_stored() -> None:
    """A database dump must not hand anybody a live code."""
    plain = new_code()
    stored = fingerprint(plain)
    assert plain not in stored
    assert len(stored) == 64


def test_the_same_code_always_fingerprints_the_same() -> None:
    assert fingerprint("ABCD2345") == fingerprint("ABCD2345")


# -------------------------------------------------------- forgiving to type --
def test_typing_is_forgiven_for_case_and_separators() -> None:
    code = _code(plain="ABCD2345")
    for typed in ("ABCD2345", "abcd2345", "ABCD-2345", "abcd 2345"):
        assert code.matches(typed), typed


def test_a_different_code_does_not_match() -> None:
    assert not _code(plain="ABCD2345").matches("ABCD2346")


def test_normalise_strips_only_the_noise() -> None:
    assert normalise(" abcd-23 45 ") == "ABCD2345"


# ------------------------------------------------------------ the alphabet --
def test_generated_codes_avoid_characters_people_confuse() -> None:
    """No 0/O/1/I/L — a code that cannot be transcribed becomes a support call."""
    for _ in range(200):
        assert not (set(new_code()) & set("01OIL"))


def test_a_generated_code_is_recognised_as_one() -> None:
    for _ in range(50):
        assert looks_like_a_code(new_code())


def test_ordinary_messages_are_not_mistaken_for_codes() -> None:
    for text in ("duyệt cp2", "chào bạn", "ABC", "ABCD23456", "mua 200 màn hình"):
        assert not looks_like_a_code(text), text


# --------------------------------------------------------------- single use --
def test_redeeming_spends_the_code() -> None:
    code = _code()
    code.redeem(external_subject="zalo-123", now=NOW)
    assert code.spent
    assert code.redeemed_subject == "zalo-123"


def test_a_spent_code_cannot_be_spent_again() -> None:
    code = _code()
    code.redeem(external_subject="zalo-123", now=NOW)
    with pytest.raises(ConflictError, match="đã được dùng"):
        code.redeem(external_subject="zalo-456", now=NOW)


# ------------------------------------------------------------- short-lived --
def test_an_expired_code_is_refused() -> None:
    code = _code(expires_in=timedelta(minutes=10))
    with pytest.raises(ConflictError, match="hết hạn"):
        code.redeem(external_subject="zalo-123", now=NOW + timedelta(minutes=11))


def test_the_last_second_still_works() -> None:
    code = _code(expires_in=timedelta(minutes=10))
    code.redeem(external_subject="zalo-123", now=NOW + timedelta(minutes=9, seconds=59))
    assert code.spent


# ------------------------------------------------------------- what it needs --
def test_a_blank_chat_account_is_refused() -> None:
    """Binding to nothing would spend a code and link no one."""
    with pytest.raises(DomainError):
        _code().redeem(external_subject="   ", now=NOW)
