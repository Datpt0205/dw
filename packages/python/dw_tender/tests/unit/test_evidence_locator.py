import pytest

from dw_tender.domain.services.evidence_locator import locate_quote

pytestmark = pytest.mark.unit

SOURCE = (
    "Năng lực: Công ty đã đạt chứng nhận ISO 9001:2015 còn hiệu lực đến tháng 12/2027.\n\n"
    "Giao hàng: cam kết giao hàng trong vòng 20 ngày kể từ ngày nhận đơn đặt hàng."
)


def test_exact_quote_is_located_with_offsets() -> None:
    quote = "chứng nhận ISO 9001:2015 còn hiệu lực đến tháng 12/2027"
    located = locate_quote(quote, SOURCE)
    assert located is not None
    assert SOURCE[located.start_offset : located.end_offset].startswith("chứng nhận ISO")
    assert len(located.source_hash) == 64


def test_whitespace_and_case_tolerant() -> None:
    quote = "CAM KẾT   giao hàng trong vòng 20 ngày"
    assert locate_quote(quote, SOURCE) is not None


def test_invented_quote_yields_no_evidence() -> None:
    assert locate_quote("giao hàng trong 5 ngày miễn phí", SOURCE) is None


def test_empty_quote_yields_none() -> None:
    assert locate_quote("   ", SOURCE) is None


def test_deterministic() -> None:
    quote = "giao hàng trong vòng 20 ngày"
    assert locate_quote(quote, SOURCE) == locate_quote(quote, SOURCE)
