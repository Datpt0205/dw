"""Tool executor: the enforcement pipeline for every tool call (blueprint §10.3).

Steps: resolve → validate input → authorize/policy → mask telemetry → execute
(timeout/retry) → validate output → audit → typed result. Side effects require
an idempotency key; replays return the stored result without re-executing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid as uuid_module
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ValidationError

from dw_agent_runtime.context import access_context_from_run
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.tools import ToolRegistry
from dw_kernel.errors import (
    ApprovalRequiredError,
    DomainError,
    IdempotencyConflictError,
    InfrastructureError,
    PermissionDeniedError,
)
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_observability.redaction import redact_mapping
from dw_platform.application.ports import PlatformUnitOfWorkFactory
from dw_platform.domain.audit import AuditEvent

SleepFn = Callable[[float], Awaitable[None]]


class ExecutionStorePort(Protocol):
    """Idempotency + audit-trail persistence for tool executions."""

    async def find_succeeded(
        self, run_context: RunContext, tool_name: str, idempotency_key: str
    ) -> object | None: ...

    async def record(
        self,
        run_context: RunContext,
        *,
        execution_id: uuid_module.UUID,
        tool_name: str,
        tool_version: str,
        status: str,
        input_hash: str,
        output_hash: str | None,
        output: dict[str, object] | None,
        idempotency_key: str | None,
        error: str | None,
        attempts: int,
        started_at: datetime,
        finished_at: datetime,
    ) -> None: ...


def _canonical_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass
class ToolExecutor:
    registry: ToolRegistry
    execution_store: ExecutionStorePort
    uow_factory: PlatformUnitOfWorkFactory
    clock: UtcClock
    id_generator: IdGenerator
    sleep: SleepFn = field(default=asyncio.sleep)
    base_backoff_seconds: float = 0.2

    async def execute(
        self,
        *,
        name: str,
        version: str,
        raw_input: dict[str, object],
        run_context: RunContext,
        idempotency_key: str | None = None,
        approved: bool = False,
    ) -> BaseModel:
        # 1. resolve
        tool = self.registry.resolve(name, version)
        definition = tool.definition

        # 2. validate input
        try:
            input_model = tool.input_model.model_validate(raw_input)
        except ValidationError as exc:
            raise DomainError(
                "tool input failed schema validation",
                details={"tool": name, "errors": str(exc.error_count())},
            ) from exc
        input_payload = input_model.model_dump(mode="json")
        input_hash = _canonical_hash(input_payload)

        # 3. authorization + approval policy
        missing = definition.required_scopes - run_context.scopes
        if missing:
            await self._audit(
                run_context,
                "tool.denied",
                definition,
                input_hash,
                policy_decision="deny_missing_scope",
                details={"missing_scopes": sorted(missing)},
            )
            raise PermissionDeniedError(
                "run context lacks required tool scopes",
                details={"tool": name, "missing_scopes": sorted(missing)},
            )
        if definition.requires_approval() and not approved:
            await self._audit(
                run_context,
                "tool.approval_required",
                definition,
                input_hash,
                policy_decision="require_approval",
            )
            raise ApprovalRequiredError(
                "tool requires human approval before execution",
                details={"tool": name, "side_effect_level": definition.side_effect_level},
            )
        if definition.side_effect_level in ("external", "critical") and not idempotency_key:
            raise DomainError(
                "side-effect tools require an idempotency key",
                details={"tool": name},
            )

        # 4. mask telemetry (never log raw payloads)
        safe_input = redact_mapping(input_payload)

        # 5a. idempotent replay
        if idempotency_key:
            existing = await self.execution_store.find_succeeded(run_context, name, idempotency_key)
            if existing is not None:
                if getattr(existing, "input_hash", None) != input_hash:
                    raise IdempotencyConflictError(
                        "idempotency key reused with a different payload",
                        details={"tool": name, "idempotency_key": idempotency_key},
                    )
                stored_output = getattr(existing, "output", None) or {}
                await self._audit(
                    run_context,
                    "tool.replayed",
                    definition,
                    input_hash,
                    policy_decision="allow",
                    details={"idempotency_key": idempotency_key},
                )
                return tool.output_model.model_validate(stored_output)

        # 5b. execute with timeout + bounded retries (retry only if idempotent)
        started_at = self.clock.now().astimezone(UTC)
        attempts_allowed = 1 + (definition.max_retries if definition.idempotent else 0)
        attempt = 0
        last_error: Exception | None = None
        output_model: BaseModel | None = None
        while attempt < attempts_allowed:
            attempt += 1
            try:
                raw_output = await asyncio.wait_for(
                    tool.handler(input_model, run_context),
                    timeout=definition.timeout_seconds,
                )
                # 6. validate output
                output_model = tool.output_model.model_validate(
                    raw_output.model_dump() if isinstance(raw_output, BaseModel) else raw_output
                )
                break
            except (TimeoutError, InfrastructureError) as exc:
                last_error = exc
                if attempt < attempts_allowed:
                    await self.sleep(self.base_backoff_seconds * (2 ** (attempt - 1)))
            except ValidationError as exc:
                last_error = DomainError(
                    "tool output failed schema validation", details={"tool": name}
                )
                last_error.__cause__ = exc
                break

        finished_at = self.clock.now().astimezone(UTC)

        if output_model is None:
            assert last_error is not None
            await self.execution_store.record(
                run_context,
                execution_id=self.id_generator.new_uuid(),
                tool_name=name,
                tool_version=version,
                status="failed",
                input_hash=input_hash,
                output_hash=None,
                output=None,
                idempotency_key=idempotency_key,
                error=type(last_error).__name__,
                attempts=attempt,
                started_at=started_at,
                finished_at=finished_at,
            )
            await self._audit(
                run_context,
                "tool.failed",
                definition,
                input_hash,
                policy_decision="allow",
                details={
                    "error": type(last_error).__name__,
                    "attempts": attempt,
                    "input": safe_input,
                },
            )
            if isinstance(last_error, DomainError):
                raise last_error
            raise InfrastructureError(
                "tool execution failed",
                details={"tool": name, "error": type(last_error).__name__},
            ) from last_error

        output_payload = output_model.model_dump(mode="json")
        output_hash = _canonical_hash(output_payload)

        # 7. persist execution + audit
        await self.execution_store.record(
            run_context,
            execution_id=self.id_generator.new_uuid(),
            tool_name=name,
            tool_version=version,
            status="succeeded",
            input_hash=input_hash,
            output_hash=output_hash,
            output=output_payload,
            idempotency_key=idempotency_key,
            error=None,
            attempts=attempt,
            started_at=started_at,
            finished_at=finished_at,
        )
        await self._audit(
            run_context,
            "tool.executed",
            definition,
            input_hash,
            policy_decision="allow",
            details={"output_hash": output_hash, "attempts": attempt},
        )

        # 8. typed result
        return output_model

    async def _audit(
        self,
        run_context: RunContext,
        action: str,
        definition: object,
        input_hash: str,
        *,
        policy_decision: str,
        details: dict[str, object] | None = None,
    ) -> None:
        tool_name = getattr(definition, "name", "unknown")
        tool_version = getattr(definition, "version", "unknown")
        event = AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(run_context.tenant_id),
            workspace_id=WorkspaceId(run_context.workspace_id),
            actor_id=UserId(run_context.actor_id),
            action=action,
            resource_type="tool",
            resource_id=f"{tool_name}@{tool_version}",
            run_id=run_context.run_id,
            policy_decision=policy_decision,
            trace_id=run_context.trace_id,
            details={"input_hash": input_hash, **(details or {})},
            occurred_at=self.clock.now().astimezone(UTC),
        )
        context = access_context_from_run(run_context)
        async with self.uow_factory(context) as uow:
            await uow.audit.append(event)
            await uow.commit()
