"""Redaction of secrets/PII before anything reaches logs, traces or audit."""

from __future__ import annotations

import re
from collections.abc import Mapping

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:^|_)(password|passwd|secret|token|api[_-]?key|authorization|credential|"
    r"private[_-]?key|client[_-]?secret|access[_-]?key|session)(?:$|_)",
    re.IGNORECASE,
)

_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)


def is_sensitive_key(key: str) -> bool:
    return _SENSITIVE_KEY_PATTERN.search(key) is not None


def redact_text(text: str) -> str:
    """Redact obvious in-line credentials from free text."""
    return _BEARER_PATTERN.sub(f"Bearer {REDACTED}", text)


def redact_mapping(data: Mapping[str, object]) -> dict[str, object]:
    """Return a copy with sensitive values replaced, recursing into nests."""
    cleaned: dict[str, object] = {}
    for key, value in data.items():
        if is_sensitive_key(key):
            cleaned[key] = REDACTED
        elif isinstance(value, Mapping):
            cleaned[key] = redact_mapping(value)
        elif isinstance(value, str):
            cleaned[key] = redact_text(value)
        else:
            cleaned[key] = value
    return cleaned
