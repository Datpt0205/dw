"""Signature verification: valid, forged, and replayed requests."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from dw_connectors.adapters.slack_signature import SlackSignatureVerifier

pytestmark = pytest.mark.unit


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def test_valid_signature_passes() -> None:
    verifier = SlackSignatureVerifier("s3cret")
    ts = str(int(time.time()))
    body = b'{"type":"event_callback"}'
    assert verifier.verify(timestamp=ts, signature=_sign("s3cret", ts, body), body=body)


def test_forged_signature_rejected() -> None:
    verifier = SlackSignatureVerifier("s3cret")
    ts = str(int(time.time()))
    body = b"{}"
    assert not verifier.verify(timestamp=ts, signature=_sign("WRONG", ts, body), body=body)


def test_replayed_timestamp_rejected() -> None:
    verifier = SlackSignatureVerifier("s3cret")
    stale = str(int(time.time()) - 3600)
    body = b"{}"
    assert not verifier.verify(timestamp=stale, signature=_sign("s3cret", stale, body), body=body)


def test_missing_parts_rejected() -> None:
    verifier = SlackSignatureVerifier("")
    assert not verifier.verify(timestamp="", signature="", body=b"{}")
