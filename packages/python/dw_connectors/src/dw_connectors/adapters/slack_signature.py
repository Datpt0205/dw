"""Slack request signature verification (P8 hardening, plan §9.5).

HMAC v0 scheme: sig = "v0=" + hex(hmac_sha256(secret, f"v0:{timestamp}:{body}")).
Stale timestamps are rejected to stop replay; comparison is constant-time.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

_MAX_SKEW_SECONDS = 60 * 5


@dataclass(frozen=True)
class SlackSignatureVerifier:
    signing_secret: str

    def verify(self, *, timestamp: str, signature: str, body: bytes) -> bool:
        if not self.signing_secret or not timestamp or not signature:
            return False
        try:
            ts = int(timestamp)
        except ValueError:
            return False
        if abs(time.time() - ts) > _MAX_SKEW_SECONDS:
            return False  # replayed or badly skewed request
        base = b"v0:" + timestamp.encode() + b":" + body
        expected = "v0=" + hmac.new(self.signing_secret.encode(), base, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
