"""Outbound URL guard fails closed on private/invalid destinations."""

from __future__ import annotations

import pytest

from dw_kernel.net_guard import OutboundUrlError, ensure_allowed_outbound_url

pytestmark = pytest.mark.unit


def test_rejects_non_http_schemes() -> None:
    for url in ("ftp://example.com", "file:///etc/passwd", "gopher://x", "not-a-url"):
        with pytest.raises(OutboundUrlError):
            ensure_allowed_outbound_url(url)


def test_rejects_embedded_credentials() -> None:
    with pytest.raises(OutboundUrlError, match="credentials"):
        ensure_allowed_outbound_url("https://user:pass@api.example.com/v1")


def test_rejects_loopback_and_private_addresses_by_default() -> None:
    for url in (
        "http://127.0.0.1:11434/v1",
        "http://localhost:8080",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "http://10.0.0.5/internal",
        "http://192.168.1.10",
        "http://0.0.0.0:9000",
    ):
        with pytest.raises(OutboundUrlError, match=r"private|resolve"):
            ensure_allowed_outbound_url(url)


def test_allow_private_permits_local_dev_providers() -> None:
    url = "http://localhost:11434/v1"
    assert ensure_allowed_outbound_url(url, allow_private=True) == url


def test_explicit_allowlist_bypasses_the_private_check() -> None:
    url = "http://localhost:11434/v1"
    assert ensure_allowed_outbound_url(url, allowed_hosts=("localhost",)) == url


def test_unresolvable_host_is_rejected() -> None:
    with pytest.raises(OutboundUrlError):
        ensure_allowed_outbound_url("https://definitely-not-a-real-host.invalid")
