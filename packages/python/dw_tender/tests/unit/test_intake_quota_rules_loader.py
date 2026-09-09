"""The rule pack that ships, and what the loader refuses.

Validation is strict here because this is the moment an operator is watching.
A mistyped threshold that loads cleanly surfaces hours later as a wrong number
in front of a user who cannot argue with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dw_kernel.errors import InfrastructureError
from dw_tender.adapters.preparation.intake_quota_rules_loader import load_intake_quota_rules

SHIPPED = (
    Path(__file__).resolve().parents[4].parent
    / "configs"
    / "policies"
    / "dw01"
    / "intake_quota_v1.yaml"
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "quota.yaml"
    path.write_text(body, encoding="utf-8")
    return path


VALID = """
schema_version: "1.0"
policy_id: dw01_intake_quota
policy_version: "1.0.0"
source: "Quy chế §4.2"
enabled_from: "2026-09-09T00:00:00+07:00"
period: calendar_month
timezone: Asia/Ho_Chi_Minh
threshold: 2
burst: {window_days: 7, threshold: 0}
count_closed_unsuccessful: false
explanation: {min_chars: 80, approver_role: procurement_head, escalate_after_hours: 48}
guidance: "Gộp lại thành một yêu cầu."
"""


# --------------------------------------------------------- what ships today --
def test_the_shipped_pack_loads() -> None:
    rules = load_intake_quota_rules(SHIPPED)
    assert rules.policy_version
    assert rules.approver_role == "procurement_head"
    assert rules.timezone == "Asia/Ho_Chi_Minh"


def test_the_shipped_pack_is_switched_off() -> None:
    """No number anyone picked for you is the right one for your company.

    A mechanism that stops people filing work must be turned on deliberately,
    with a regulation named in ``source``.
    """
    rules = load_intake_quota_rules(SHIPPED)
    assert not rules.is_enabled(), "ship disabled; procurement sets the threshold"


# ------------------------------------------------------------- what it takes --
def test_a_valid_pack_parses_every_field(tmp_path: Path) -> None:
    rules = load_intake_quota_rules(_write(tmp_path, VALID))
    assert rules.threshold == 2
    assert rules.count_closed_unsuccessful is False
    assert rules.explanation_min_chars == 80
    assert rules.escalate_after_hours == 48
    assert rules.enabled_from is not None and rules.enabled_from.tzinfo is not None
    assert rules.is_enabled()


# ------------------------------------------------------------ what it refuses --
def test_an_unknown_timezone_is_refused_at_startup(tmp_path: Path) -> None:
    body = VALID.replace("Asia/Ho_Chi_Minh", "Asia/Hanoi_Typo")
    with pytest.raises(InfrastructureError, match="not a known zone"):
        load_intake_quota_rules(_write(tmp_path, body))


def test_a_naive_enabled_from_is_refused(tmp_path: Path) -> None:
    """Without an offset there is no telling which day it means."""
    body = VALID.replace('"2026-09-09T00:00:00+07:00"', '"2026-09-09T00:00:00"')
    with pytest.raises(InfrastructureError, match="offset"):
        load_intake_quota_rules(_write(tmp_path, body))


def test_a_rolling_window_is_refused(tmp_path: Path) -> None:
    """Only calendar_month is implemented; silently ignoring the key would
    enforce a different rule than the one written in the file."""
    body = VALID.replace("period: calendar_month", "period: rolling_30_days")
    with pytest.raises(InfrastructureError, match="period"):
        load_intake_quota_rules(_write(tmp_path, body))


def test_a_missing_threshold_is_refused_by_name(tmp_path: Path) -> None:
    body = VALID.replace("threshold: 2\n", "")
    with pytest.raises(InfrastructureError, match="threshold"):
        load_intake_quota_rules(_write(tmp_path, body))


def test_a_missing_approver_role_is_refused(tmp_path: Path) -> None:
    body = VALID.replace("approver_role: procurement_head, ", "")
    with pytest.raises(InfrastructureError, match="approver_role"):
        load_intake_quota_rules(_write(tmp_path, body))


def test_an_unsupported_schema_is_refused(tmp_path: Path) -> None:
    body = VALID.replace('schema_version: "1.0"', 'schema_version: "2.0"')
    with pytest.raises(InfrastructureError, match="schema"):
        load_intake_quota_rules(_write(tmp_path, body))
