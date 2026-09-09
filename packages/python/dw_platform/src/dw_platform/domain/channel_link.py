"""A one-time code that ties a chat account to a corporate identity.

The problem it removes: a hand-maintained file mapping Zalo user ids to people.
Fine for three people in a demo, impossible for three hundred, and wrong from
the first day someone joins or leaves.

The exchange runs the other way round from a login. The person is already
authenticated on the web — SSO has established who they are — and what is
unknown is which chat account belongs to them. So the server mints a code for a
known person, and the chat account proves itself by quoting it back. Nothing
about the person is taken from the chat side; the only thing learned there is
"this Zalo id is the one that had the code".

Three properties do the security work, and none of them are optional:

* **Short-lived.** The window is minutes, because the code travels through a
  screen and a chat app and may be seen by whoever is standing there.
* **Single-use.** A redeemed code is spent even if the binding then fails, so a
  code seen over a shoulder is worth nothing once used.
* **Never stored in the clear.** Only a hash is kept. A database dump then does
  not hand anybody a live code, and the code exists in readable form for
  exactly as long as it is on the person's screen.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from dw_kernel.errors import ConflictError, DomainError

# No 0/O/1/I/L. People read these off a screen and type them into a phone, and
# a code that cannot be transcribed reliably turns into a support ticket.
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_LENGTH = 8

# Long enough to walk from a laptop to a phone, short enough that a shoulder
# glance goes stale.
DEFAULT_TTL = timedelta(minutes=10)


def new_code() -> str:
    """A fresh code, in the form the person will read off their screen."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))


def fingerprint(code: str) -> str:
    """What gets stored. Normalised first so typing is forgiving.

    Case and separators are noise a person adds; treating "abcd-efgh" and
    "ABCDEFGH" as different codes would fail the transcription this format was
    designed to survive.
    """
    return hashlib.sha256(normalise(code).encode()).hexdigest()


def normalise(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def looks_like_a_code(text: str) -> bool:
    """Is this message shaped like a code we issued?

    A format check on something the server minted, not a guess at what somebody
    meant — the alphabet and length are ours. It only decides whether redeeming
    is worth attempting; a wrong guess costs one failed lookup.

    A code is one word. That is not cosmetic: "duyet cp2" — the commonest
    command in the system, typed the way Vietnamese is typed in chat, without
    diacritics — is eight characters from this very alphabet once spaces are
    stripped. Someone not yet linked would have been told their code was wrong
    instead of being told how to link.
    """
    if len(text.split()) != 1:
        return False
    candidate = normalise(text)
    return len(candidate) == _LENGTH and all(ch in _ALPHABET for ch in candidate)


@dataclass
class ChannelLinkCode:
    """One issued code, and the single decision it can make."""

    id: UUID
    code_hash: str
    user_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    issuer: str
    expires_at: datetime
    created_at: datetime
    redeemed_at: datetime | None = None
    redeemed_subject: str = ""

    @property
    def spent(self) -> bool:
        return self.redeemed_at is not None

    def matches(self, code: str) -> bool:
        """Constant-time, so a wrong code cannot be narrowed by timing."""
        return hmac.compare_digest(self.code_hash, fingerprint(code))

    def redeem(self, *, external_subject: str, now: datetime) -> None:
        """Spend this code against one chat account.

        Spent before the binding is attempted, not after. A code that failed to
        bind — because that chat account already belongs to someone else — must
        not be reusable, or a failed attempt would leave a live code behind.
        """
        subject = external_subject.strip()
        if not subject:
            raise DomainError("cần định danh tài khoản chat để liên kết")
        if self.spent:
            raise ConflictError("mã này đã được dùng rồi")
        if now >= self.expires_at:
            raise ConflictError("mã đã hết hạn")
        self.redeemed_at = now
        self.redeemed_subject = subject
