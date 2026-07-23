import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from dw_memory.contracts import MEMORY_SCHEMA_VERSION, MemoryItem, MemoryType

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def make_item(**overrides: object) -> MemoryItem:
    defaults: dict[str, object] = {
        "memory_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "worker_id": "work_ops",
        "memory_type": MemoryType.COMMITMENT,
        "content": "Phòng Mua hàng cam kết phản hồi RFQ trong 5 ngày.",
        "confidence": 0.9,
        "valid_from": NOW,
        "created_by_run_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return MemoryItem(**defaults)


def test_memory_carries_schema_version() -> None:
    assert make_item().memory_schema_version == MEMORY_SCHEMA_VERSION


def test_validity_window_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        make_item(valid_until=NOW - timedelta(days=1))


def test_is_valid_at_respects_window() -> None:
    item = make_item(valid_until=NOW + timedelta(days=30))
    assert item.is_valid_at(NOW + timedelta(days=1))
    assert not item.is_valid_at(NOW - timedelta(days=1))
    assert not item.is_valid_at(NOW + timedelta(days=31))


def test_confidence_bounded() -> None:
    with pytest.raises(ValidationError):
        make_item(confidence=1.2)


def test_empty_content_rejected() -> None:
    with pytest.raises(ValidationError):
        make_item(content="")
