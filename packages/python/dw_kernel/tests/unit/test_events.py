import uuid
from datetime import UTC, datetime

import pytest

from dw_kernel.events import DomainEvent
from dw_kernel.ids import TenantId, WorkspaceId

pytestmark = pytest.mark.unit


def _make_event(**overrides: object) -> DomainEvent:
    defaults: dict[str, object] = {
        "event_id": uuid.uuid4(),
        "occurred_at": datetime(2026, 7, 23, 9, 0, tzinfo=UTC),
        "tenant_id": TenantId(uuid.uuid4()),
        "workspace_id": WorkspaceId(uuid.uuid4()),
        "aggregate_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return DomainEvent(**defaults)  # type: ignore[arg-type]


def test_event_is_immutable() -> None:
    event = _make_event()
    with pytest.raises(AttributeError):
        event.aggregate_id = uuid.uuid4()  # type: ignore[misc]


def test_event_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _make_event(occurred_at=datetime(2026, 7, 23, 9, 0))


def test_event_type_and_schema_version_are_class_contracts() -> None:
    event = _make_event()
    assert event.event_type == "kernel.domain_event"
    assert event.schema_version == "1.0"
