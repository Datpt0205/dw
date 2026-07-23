"""Money value object with same-currency arithmetic invariants."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not self.currency or len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError(f"currency must be a 3-letter ISO code, got {self.currency!r}")
        object.__setattr__(self, "currency", self.currency.upper())
        if not isinstance(self.amount, Decimal):
            raise TypeError("amount must be a Decimal")

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def add(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def subtract(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def is_negative(self) -> bool:
        return self.amount < 0
