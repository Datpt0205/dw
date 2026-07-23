"""Minimal Result type for use-case outcomes that are expected, not exceptional."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        return self.value

    def map[U](self, fn: Callable[[T], U]) -> Ok[U]:
        return Ok(fn(self.value))


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def unwrap(self) -> NoReturn:
        raise RuntimeError(f"Called unwrap() on Err({self.error!r})")

    def map(self, fn: Callable[[object], object]) -> Err[E]:
        return self


type Result[T, E] = Ok[T] | Err[E]
