"""Universal ports (clock, id generation) with stdlib default adapters.

Domain and application code depend on these protocols; production and test
composition roots choose the implementation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol


class UtcClock(Protocol):
    """Provides the current UTC time."""

    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    """Generates new unique identifiers."""

    def new_uuid(self) -> uuid.UUID: ...


class SystemClock:
    """Wall-clock implementation of :class:`UtcClock`."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


@dataclass
class FixedClock:
    """Deterministic clock for tests; advances only when told to."""

    current: datetime

    def now(self) -> datetime:
        if self.current.tzinfo is None:
            raise ValueError("FixedClock requires an aware datetime")
        return self.current

    def advance_to(self, moment: datetime) -> None:
        self.current = moment


class Uuid4Generator:
    """Random UUID implementation of :class:`IdGenerator`."""

    def new_uuid(self) -> uuid.UUID:
        return uuid.uuid4()


@dataclass
class SequentialIdGenerator:
    """Deterministic id generator for tests."""

    _counter: int = 0
    issued: list[uuid.UUID] = field(default_factory=list)

    def new_uuid(self) -> uuid.UUID:
        self._counter += 1
        generated = uuid.UUID(int=self._counter)
        self.issued.append(generated)
        return generated
