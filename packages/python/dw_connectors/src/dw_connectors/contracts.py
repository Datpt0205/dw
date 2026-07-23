"""Canonical connector contracts (anti-corruption layer boundary).

Slack ``user_id``, Teams ``aadObjectId`` and HR ``employee_code`` all map to
``OrganizationPersonRef``; raw provider payloads never become domain entities.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrganizationPersonRef(BaseModel):
    """Canonical reference to a person across external systems."""

    model_config = ConfigDict(frozen=True)

    person_id: UUID
    display_name: str
    department_id: UUID | None = None
    external_identities: dict[str, str] = {}  # e.g. {"slack": "U123", "teams": "aad-guid"}


class CreateExternalTask(BaseModel):
    """Command to create a task in an external system (canonical shape)."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    workspace_id: UUID
    action_item_id: UUID
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    assignee: OrganizationPersonRef
    due_date: datetime | None = None
    priority: str = "normal"


class ExternalTaskRef(BaseModel):
    """Reference to a task that exists in an external system."""

    model_config = ConfigDict(frozen=True)

    connector: str
    connector_version: str
    external_id: str
    external_url: str | None = None
    created_at: datetime
