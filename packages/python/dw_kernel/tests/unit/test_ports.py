import uuid
from datetime import UTC, datetime

import pytest

from dw_kernel.ports import FixedClock, SequentialIdGenerator, SystemClock, Uuid4Generator

pytestmark = pytest.mark.unit


def test_system_clock_returns_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC


def test_fixed_clock_is_deterministic_and_advances() -> None:
    start = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    clock = FixedClock(start)
    assert clock.now() == start
    later = datetime(2026, 7, 23, 13, 0, tzinfo=UTC)
    clock.advance_to(later)
    assert clock.now() == later


def test_fixed_clock_rejects_naive_datetime() -> None:
    clock = FixedClock(datetime(2026, 7, 23, 12, 0))
    with pytest.raises(ValueError, match="aware"):
        clock.now()


def test_uuid4_generator_returns_unique_ids() -> None:
    gen = Uuid4Generator()
    assert gen.new_uuid() != gen.new_uuid()


def test_sequential_generator_is_deterministic() -> None:
    gen = SequentialIdGenerator()
    first, second = gen.new_uuid(), gen.new_uuid()
    assert first == uuid.UUID(int=1)
    assert second == uuid.UUID(int=2)
    assert gen.issued == [first, second]
