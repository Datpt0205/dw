"""Loads the DW01 intake-quota rule pack (YAML) into ``IntakeQuotaRules``.

Its own file, and its own ``policy_version`` counter, for the same reason the
rework pack has one: a decision that stopped somebody from filing has to be
traceable to the exact thresholds in force at that moment, and those move on
different schedules.

Validation is strict at startup and lenient at runtime. A mistyped threshold
should fail the process here, where an operator is watching, rather than
surface hours later as a wrong number in front of a user.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from dw_kernel.errors import InfrastructureError
from dw_tender.application.preparation.intake_quota import IntakeQuotaRules

_SUPPORTED_SCHEMA = "1.0"
_SUPPORTED_PERIOD = "calendar_month"


def _int_at(data: dict[str, Any], key: str, path: Path, *, section: str = "") -> int:
    block: Any = data
    label = key
    if section:
        block = data.get(section)
        label = f"{section}.{key}"
        if not isinstance(block, dict):
            raise InfrastructureError(f"intake quota rule pack missing {section}: {path}")
    if key not in block:
        raise InfrastructureError(f"intake quota rule pack missing {label}: {path}")
    try:
        return int(block[key])
    except (TypeError, ValueError) as exc:
        raise InfrastructureError(
            f"intake quota rule pack {label} must be an integer: {path}"
        ) from exc


def _parse_enabled_from(raw: Any, path: Path) -> datetime | None:
    if raw in (None, ""):
        return None
    moment = raw if isinstance(raw, datetime) else None
    if moment is None:
        try:
            moment = datetime.fromisoformat(str(raw))
        except ValueError as exc:
            raise InfrastructureError(
                f"intake quota rule pack enabled_from is not a datetime: {path}"
            ) from exc
    if moment.tzinfo is None:
        raise InfrastructureError(f"intake quota rule pack enabled_from needs an offset: {path}")
    return moment


def load_intake_quota_rules(path: Path) -> IntakeQuotaRules:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InfrastructureError(f"intake quota rule pack unreadable: {path}") from exc
    if not isinstance(raw, dict):
        raise InfrastructureError(f"intake quota rule pack is not a mapping: {path}")

    schema = str(raw.get("schema_version", ""))
    if schema != _SUPPORTED_SCHEMA:
        raise InfrastructureError(
            f"intake quota rule pack schema {schema!r} unsupported "
            f"(expected {_SUPPORTED_SCHEMA!r}): {path}"
        )

    period = str(raw.get("period", ""))
    if period != _SUPPORTED_PERIOD:
        raise InfrastructureError(
            f"intake quota rule pack period {period!r} unsupported "
            f"(expected {_SUPPORTED_PERIOD!r}): {path}"
        )

    zone = str(raw.get("timezone", "")).strip()
    if not zone:
        raise InfrastructureError(f"intake quota rule pack needs a timezone: {path}")
    try:
        ZoneInfo(zone)
    except Exception as exc:
        raise InfrastructureError(
            f"intake quota rule pack timezone {zone!r} is not a known zone: {path}"
        ) from exc

    explanation = raw.get("explanation")
    if not isinstance(explanation, dict):
        raise InfrastructureError(f"intake quota rule pack missing explanation: {path}")
    approver_role = str(explanation.get("approver_role", "")).strip()
    if not approver_role:
        raise InfrastructureError(f"intake quota rule pack needs explanation.approver_role: {path}")

    return IntakeQuotaRules(
        policy_version=str(raw.get("policy_version", "")),
        source=str(raw.get("source", "")).strip(),
        enabled_from=_parse_enabled_from(raw.get("enabled_from"), path),
        timezone=zone,
        threshold=_int_at(raw, "threshold", path),
        burst_window_days=_int_at(raw, "window_days", path, section="burst"),
        burst_threshold=_int_at(raw, "threshold", path, section="burst"),
        count_closed_unsuccessful=bool(raw.get("count_closed_unsuccessful", False)),
        explanation_min_chars=_int_at(raw, "min_chars", path, section="explanation"),
        approver_role=approver_role,
        escalate_after_hours=_int_at(raw, "escalate_after_hours", path, section="explanation"),
        guidance=str(raw.get("guidance", "")).strip(),
    )
