"""Circuit breaker: protect callers from a repeatedly failing dependency.

Pure stdlib, clock-injected (deterministic in tests). States:

- CLOSED: calls flow; consecutive failures are counted.
- OPEN: calls are refused immediately until ``reset_timeout`` elapses.
- HALF_OPEN: one trial call is allowed; success closes, failure re-opens.

The breaker only counts failures the caller reports via ``record_failure`` —
business rejections (e.g. validation) should not trip it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from dw_kernel.errors import InfrastructureError
from dw_kernel.ports import UtcClock


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(InfrastructureError):
    """Raised when the breaker refuses a call without attempting it."""


@dataclass
class CircuitBreaker:
    """Not thread-safe by design: one breaker per adapter per event loop."""

    clock: UtcClock
    name: str
    failure_threshold: int = 5
    reset_timeout_seconds: float = 30.0
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: datetime | None = field(default=None, init=False)

    @property
    def state(self) -> CircuitState:
        return self._state

    def before_call(self) -> None:
        """Raise ``CircuitOpenError`` unless a call may proceed right now."""
        if self._state is CircuitState.CLOSED:
            return
        if self._state is CircuitState.OPEN:
            assert self._opened_at is not None
            elapsed = (self.clock.now() - self._opened_at).total_seconds()
            if elapsed < self.reset_timeout_seconds:
                raise CircuitOpenError(
                    "circuit breaker is open",
                    details={
                        "breaker": self.name,
                        "retry_after_seconds": str(max(0.0, self.reset_timeout_seconds - elapsed)),
                    },
                )
            self._state = CircuitState.HALF_OPEN  # one trial call allowed

    def record_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        if self._state is CircuitState.HALF_OPEN:
            self._trip()
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self.clock.now()
        self._consecutive_failures = 0
