import pytest

from dw_kernel.errors import (
    ApprovalRequiredError,
    DWError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
    TenantContextMissingError,
)

pytestmark = pytest.mark.unit


def test_every_error_carries_stable_code() -> None:
    assert NotFoundError("x").code is ErrorCode.NOT_FOUND
    assert PermissionDeniedError("x").code is ErrorCode.PERMISSION_DENIED
    assert ApprovalRequiredError("x").code is ErrorCode.APPROVAL_REQUIRED
    assert TenantContextMissingError("x").code is ErrorCode.TENANT_CONTEXT_MISSING


def test_details_default_to_empty_dict_not_shared() -> None:
    first, second = DWError("a"), DWError("b")
    first.details["k"] = "v"
    assert second.details == {}


def test_errors_are_exceptions_with_message() -> None:
    err = NotFoundError("meeting not found", details={"meeting_id": "m1"})
    assert str(err) == "meeting not found"
    assert err.details == {"meeting_id": "m1"}
    assert isinstance(err, DWError)
