import uuid

import pytest

from dw_kernel.ids import EntityId, TenantId, UserId, WorkspaceId

pytestmark = pytest.mark.unit


def test_from_string_roundtrip() -> None:
    raw = str(uuid.uuid4())
    tenant = TenantId.from_string(raw)
    assert str(tenant) == raw
    assert isinstance(tenant.value, uuid.UUID)


def test_from_string_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="TenantId requires a valid UUID"):
        TenantId.from_string("not-a-uuid")


def test_ids_are_immutable() -> None:
    tenant = TenantId(uuid.uuid4())
    with pytest.raises(AttributeError):
        tenant.value = uuid.uuid4()  # type: ignore[misc]


def test_distinct_id_types_are_not_equal_even_with_same_uuid() -> None:
    shared = uuid.uuid4()
    tenant: object = TenantId(shared)
    workspace: object = WorkspaceId(shared)
    assert tenant != workspace
    user: object = UserId(shared)
    entity: object = EntityId(shared)
    assert user != entity


def test_same_type_same_uuid_is_equal() -> None:
    shared = uuid.uuid4()
    assert TenantId(shared) == TenantId(shared)
    assert hash(TenantId(shared)) == hash(TenantId(shared))
