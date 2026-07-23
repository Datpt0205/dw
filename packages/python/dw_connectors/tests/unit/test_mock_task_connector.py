import uuid

import pytest

from dw_connectors.adapters.mock_task_connector import MockTaskConnectorAdapter
from dw_connectors.contracts import CreateExternalTask, OrganizationPersonRef
from dw_kernel.errors import IdempotencyConflictError

pytestmark = pytest.mark.unit


def make_command(title: str = "Chuẩn bị báo cáo tuần") -> CreateExternalTask:
    return CreateExternalTask(
        tenant_id=uuid.UUID(int=1),
        workspace_id=uuid.UUID(int=2),
        action_item_id=uuid.UUID(int=3),
        title=title,
        assignee=OrganizationPersonRef(
            person_id=uuid.UUID(int=4),
            display_name="Nguyễn Văn A",
            external_identities={"slack": "U0001"},
        ),
    )


async def test_creates_task_and_returns_reference() -> None:
    connector = MockTaskConnectorAdapter()
    ref = await connector.create_task(make_command(), idempotency_key="t1:a1:mock:1")
    assert ref.connector == "mock"
    assert ref.external_id.startswith("MOCK-")
    assert connector.created_count() == 1


async def test_retry_with_same_key_is_idempotent() -> None:
    connector = MockTaskConnectorAdapter()
    key = "tenant:action:mock:1.0.0"
    first = await connector.create_task(make_command(), idempotency_key=key)
    second = await connector.create_task(make_command(), idempotency_key=key)
    assert first == second
    assert connector.created_count() == 1


async def test_same_key_different_payload_conflicts() -> None:
    connector = MockTaskConnectorAdapter()
    key = "tenant:action:mock:1.0.0"
    await connector.create_task(make_command("A"), idempotency_key=key)
    with pytest.raises(IdempotencyConflictError):
        await connector.create_task(make_command("B"), idempotency_key=key)
