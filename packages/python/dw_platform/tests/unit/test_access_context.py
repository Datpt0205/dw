import uuid

import pytest
from pydantic import ValidationError

from dw_platform.application.access_context import AccessContext

pytestmark = pytest.mark.unit


def make_context(**overrides: object) -> AccessContext:
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "principal_id": uuid.uuid4(),
        "roles": frozenset({"member"}),
        "scopes": frozenset({"work_ops.read"}),
        "plan_id": "professional",
    }
    defaults.update(overrides)
    return AccessContext(**defaults)


def test_context_is_frozen() -> None:
    ctx = make_context()
    with pytest.raises(ValidationError):
        ctx.tenant_id = uuid.uuid4()  # type: ignore[misc]


def test_scope_role_feature_helpers() -> None:
    ctx = make_context(
        roles=frozenset({"approver"}),
        feature_flags=frozenset({"tender_worker"}),
    )
    assert ctx.has_any_role("approver", "admin")
    assert not ctx.has_any_role("admin")
    assert ctx.has_scope("work_ops.read")
    assert not ctx.has_scope("work_ops.write")
    assert ctx.has_feature("tender_worker")


def test_blank_plan_id_rejected() -> None:
    with pytest.raises(ValidationError):
        make_context(plan_id="  ")


def test_client_supplied_tenant_is_just_data_not_trusted() -> None:
    """The model accepts any UUID; trust is established by the factory port,
    which must check membership. This test documents that contract."""
    ctx = make_context()
    assert isinstance(ctx.tenant_id, uuid.UUID)
