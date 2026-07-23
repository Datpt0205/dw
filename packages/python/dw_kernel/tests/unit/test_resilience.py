"""Circuit breaker state machine with a deterministic clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dw_kernel.ports import FixedClock
from dw_kernel.resilience import CircuitBreaker, CircuitOpenError, CircuitState

pytestmark = pytest.mark.unit

T0 = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


def make_breaker(clock: FixedClock) -> CircuitBreaker:
    return CircuitBreaker(clock=clock, name="test", failure_threshold=3, reset_timeout_seconds=30)


def state_of(breaker: CircuitBreaker) -> CircuitState:
    """Fresh read per assertion (avoids mypy literal-narrowing on properties)."""
    return breaker.state


def test_opens_after_threshold_consecutive_failures() -> None:
    breaker = make_breaker(FixedClock(T0))
    for _ in range(2):
        breaker.before_call()
        breaker.record_failure()
    assert state_of(breaker) is CircuitState.CLOSED
    breaker.record_failure()
    assert state_of(breaker) is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_call()


def test_success_resets_the_failure_count() -> None:
    breaker = make_breaker(FixedClock(T0))
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED


def test_half_open_after_timeout_then_closes_on_success() -> None:
    clock = FixedClock(T0)
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance_to(T0 + timedelta(seconds=31))
    breaker.before_call()  # trial call allowed
    assert state_of(breaker) is CircuitState.HALF_OPEN
    breaker.record_success()
    assert state_of(breaker) is CircuitState.CLOSED


def test_half_open_failure_reopens_immediately() -> None:
    clock = FixedClock(T0)
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance_to(T0 + timedelta(seconds=31))
    breaker.before_call()
    breaker.record_failure()
    assert state_of(breaker) is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_call()
