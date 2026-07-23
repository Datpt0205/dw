from decimal import Decimal

import pytest

from dw_kernel.money import Money
from dw_kernel.pagination import Cursor, Page, PageRequest

pytestmark = pytest.mark.unit


def test_money_add_same_currency() -> None:
    total = Money(Decimal("10.50"), "VND").add(Money(Decimal("2.25"), "vnd"))
    assert total == Money(Decimal("12.75"), "VND")


def test_money_rejects_currency_mismatch() -> None:
    with pytest.raises(ValueError, match="currency mismatch"):
        Money(Decimal(1), "USD").add(Money(Decimal(1), "VND"))


def test_money_rejects_bad_currency_code() -> None:
    with pytest.raises(ValueError, match="ISO code"):
        Money(Decimal(1), "DONG")


def test_cursor_roundtrip_and_invalid_token() -> None:
    cursor = Cursor.encode("offset:42")
    assert cursor.decode() == "offset:42"
    with pytest.raises(ValueError, match="invalid cursor"):
        Cursor("!!!not-base64!!!").decode()


def test_page_request_bounds() -> None:
    assert PageRequest(size=1).size == 1
    with pytest.raises(ValueError, match="page size"):
        PageRequest(size=0)
    with pytest.raises(ValueError, match="page size"):
        PageRequest(size=201)


def test_page_has_more_follows_cursor() -> None:
    assert Page(items=[1], next_cursor=Cursor.encode("x")).has_more
    assert not Page(items=[1]).has_more
