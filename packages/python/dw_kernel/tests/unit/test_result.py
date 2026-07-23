import pytest

from dw_kernel.result import Err, Ok

pytestmark = pytest.mark.unit


def test_ok_unwrap_and_map() -> None:
    result = Ok(2).map(lambda x: x * 3)
    assert result.is_ok() and not result.is_err()
    assert result.unwrap() == 6


def test_err_unwrap_raises_and_map_is_noop() -> None:
    result: Err[str] = Err("boom")
    assert result.is_err() and not result.is_ok()
    assert result.map(lambda x: x) is result
    with pytest.raises(RuntimeError, match="boom"):
        result.unwrap()
