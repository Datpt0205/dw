"""Outbound URL guard (SSRF defence for connectors and provider adapters).

Fail closed: only http(s), no credentials in the URL, and the host must not
resolve into private/loopback/link-local space unless the deployment explicitly
allows it (local dev against Ollama/vLLM) or the host is allow-listed.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from dw_kernel.errors import DomainError


class OutboundUrlError(DomainError):
    """The URL must not be called from this process."""


def _is_private_address(host: str) -> bool:
    try:
        addresses = {str(info[4][0]) for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise OutboundUrlError("outbound host does not resolve", details={"host": host}) from exc
    for raw in addresses:
        address = ipaddress.ip_address(raw.split("%")[0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_unspecified
        ):
            return True
    return False


def ensure_allowed_outbound_url(
    url: str,
    *,
    allow_private: bool = False,
    allowed_hosts: tuple[str, ...] = (),
) -> str:
    """Validate an outbound base URL; returns it unchanged when acceptable."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise OutboundUrlError(
            "outbound URL must be http(s)", details={"scheme": parts.scheme or "<none>"}
        )
    if not parts.hostname:
        raise OutboundUrlError("outbound URL has no host", details={"url": url})
    if parts.username or parts.password:
        raise OutboundUrlError(
            "outbound URL must not embed credentials", details={"host": parts.hostname}
        )
    host = parts.hostname
    if host in allowed_hosts:
        return url
    if not allow_private and _is_private_address(host):
        raise OutboundUrlError(
            "outbound URL resolves to a private address",
            details={"host": host},
        )
    return url
