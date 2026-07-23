"""The task.create_external tool: dispatch an action through a TaskConnector.

Registered in the tool registry so EVERY dispatch passes the 8-step executor
pipeline (authz, approval, idempotency, audit). The handler wraps the canonical
connector port — Slack/Teams/Jira adapters swap in without touching this file.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.tools import RegisteredTool
from dw_connectors.contracts import CreateExternalTask, OrganizationPersonRef
from dw_connectors.ports import TaskConnectorPort

TOOL_NAME = "task.create_external"
TOOL_VERSION = "1.0.0"


class CreateExternalTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    assignee_person_id: uuid.UUID
    assignee_display_name: str
    due_date: datetime | None = None


class CreateExternalTaskOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector: str
    connector_version: str
    external_id: str
    external_url: str | None = None


DISPATCH_TOOL_DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    version=TOOL_VERSION,
    description="Create a task in the connected external work-management system",
    input_schema_ref=f"contracts/tools/{TOOL_NAME}/{TOOL_VERSION}/input.json",
    output_schema_ref=f"contracts/tools/{TOOL_NAME}/{TOOL_VERSION}/output.json",
    required_scopes=frozenset({"work_ops.write"}),
    side_effect_level="external",
    approval_policy="always",  # dispatch always follows a human decision (A2)
    timeout_seconds=30,
    max_retries=2,
    idempotent=True,
    data_classification=frozenset({"internal"}),
)


@dataclass(frozen=True)
class DispatchToolFactory:
    connector: TaskConnectorPort

    def build(self) -> RegisteredTool:
        async def handler(payload: BaseModel, run_context: RunContext) -> BaseModel:
            assert isinstance(payload, CreateExternalTaskInput)
            command = CreateExternalTask(
                tenant_id=run_context.tenant_id,
                workspace_id=run_context.workspace_id,
                action_item_id=payload.action_id,
                title=payload.title,
                description=payload.description,
                assignee=OrganizationPersonRef(
                    person_id=payload.assignee_person_id,
                    display_name=payload.assignee_display_name,
                ),
                due_date=payload.due_date,
            )
            idempotency_key = (
                f"{run_context.tenant_id}:{payload.action_id}:"
                f"{self.connector.connector_name}:{TOOL_VERSION}"
            )
            ref = await self.connector.create_task(command, idempotency_key)
            return CreateExternalTaskOutput(
                connector=ref.connector,
                connector_version=ref.connector_version,
                external_id=ref.external_id,
                external_url=ref.external_url,
            )

        return RegisteredTool(
            definition=DISPATCH_TOOL_DEFINITION,
            input_model=CreateExternalTaskInput,
            output_model=CreateExternalTaskOutput,
            handler=handler,
        )
