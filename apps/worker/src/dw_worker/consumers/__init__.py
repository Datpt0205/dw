"""Consumer registry.

Consumers (outbox processor, workflow resume queue) register here in phase 2/3.
The registry is typed and fail-fast: duplicate names are rejected.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

ConsumerFn = Callable[[], Awaitable[None]]


@dataclass
class ConsumerRegistry:
    _consumers: dict[str, ConsumerFn] = field(default_factory=dict)

    def register(self, name: str, consumer: ConsumerFn) -> None:
        if not name.strip():
            raise ValueError("consumer name must not be blank")
        if name in self._consumers:
            raise ValueError(f"consumer {name!r} is already registered")
        self._consumers[name] = consumer

    def all(self) -> dict[str, ConsumerFn]:
        return dict(self._consumers)
