"""Connector ports implemented by provider adapters and the mock."""

from __future__ import annotations

from typing import Protocol

from dw_connectors.contracts import CreateExternalTask, ExternalTaskRef


class TaskConnectorPort(Protocol):
    """Creates tasks in an external work-management system.

    Implementations MUST be idempotent on ``idempotency_key``: retrying the
    same key returns the original reference and never creates a duplicate.
    """

    @property
    def connector_name(self) -> str: ...

    async def create_task(
        self,
        command: CreateExternalTask,
        idempotency_key: str,
    ) -> ExternalTaskRef: ...
