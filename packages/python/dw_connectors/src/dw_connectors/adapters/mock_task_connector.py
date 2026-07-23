"""Fully-working in-memory task connector used by the POC demo flow.

Not a stub: it enforces idempotency semantics (same key → same reference,
conflicting payload → error) exactly as real adapters must.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from dw_connectors.contracts import CreateExternalTask, ExternalTaskRef
from dw_kernel.errors import IdempotencyConflictError
from dw_kernel.ports import IdGenerator, SystemClock, UtcClock, Uuid4Generator

CONNECTOR_NAME = "mock"
CONNECTOR_VERSION = "1.0.0"


@dataclass
class MockTaskConnectorAdapter:
    """In-memory implementation of ``TaskConnectorPort``."""

    clock: UtcClock = field(default_factory=SystemClock)
    id_generator: IdGenerator = field(default_factory=Uuid4Generator)
    _store: dict[str, tuple[str, ExternalTaskRef]] = field(default_factory=dict)

    @property
    def connector_name(self) -> str:
        return CONNECTOR_NAME

    async def create_task(
        self,
        command: CreateExternalTask,
        idempotency_key: str,
    ) -> ExternalTaskRef:
        payload_fingerprint = command.model_dump_json()
        existing = self._store.get(idempotency_key)
        if existing is not None:
            stored_fingerprint, stored_ref = existing
            if stored_fingerprint != payload_fingerprint:
                raise IdempotencyConflictError(
                    "idempotency key reused with a different payload",
                    details={"idempotency_key": idempotency_key},
                )
            return stored_ref

        external_id = f"MOCK-{self.id_generator.new_uuid().hex[:12]}"
        ref = ExternalTaskRef(
            connector=CONNECTOR_NAME,
            connector_version=CONNECTOR_VERSION,
            external_id=external_id,
            external_url=f"https://mock.local/tasks/{external_id}",
            created_at=self._now(),
        )
        self._store[idempotency_key] = (payload_fingerprint, ref)
        return ref

    def created_count(self) -> int:
        """Number of distinct tasks actually created (test/inspection helper)."""
        return len(self._store)

    def _now(self) -> datetime:
        now = self.clock.now()
        return now if now.tzinfo else now.replace(tzinfo=UTC)
