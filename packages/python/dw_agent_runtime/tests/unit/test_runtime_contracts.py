import uuid

import pytest
from pydantic import ValidationError

from dw_agent_runtime.contracts import RunContext, ToolDefinition, WorkerDefinition

pytestmark = pytest.mark.unit


def make_worker(**overrides: object) -> WorkerDefinition:
    defaults: dict[str, object] = {
        "worker_id": "work_ops",
        "worker_version": "1.0.0",
        "domain": "work_ops",
        "graph_version": "1.0.0",
        "prompt_bundle_version": "1.0.0",
        "toolset_version": "1.0.0",
        "policy_version": "1.0.0",
        "memory_policy_version": "1.0.0",
        "default_model_profile": "balanced",
        "supported_channels": frozenset({"web"}),
        "autonomy_level": "A2",
    }
    defaults.update(overrides)
    return WorkerDefinition(**defaults)


def make_tool(**overrides: object) -> ToolDefinition:
    defaults: dict[str, object] = {
        "name": "task.prepare",
        "version": "1.0.0",
        "description": "Prepare a task draft",
        "input_schema_ref": "contracts/tools/task.prepare/1.0.0/input.json",
        "output_schema_ref": "contracts/tools/task.prepare/1.0.0/output.json",
        "required_scopes": frozenset({"work_ops.write"}),
        "side_effect_level": "internal",
        "approval_policy": "conditional",
        "timeout_seconds": 30,
        "max_retries": 2,
        "idempotent": True,
        "data_classification": frozenset({"internal"}),
    }
    defaults.update(overrides)
    return ToolDefinition(**defaults)


def test_worker_definition_is_frozen_and_versioned() -> None:
    worker = make_worker()
    with pytest.raises(ValidationError):
        worker.worker_version = "2.0.0"  # type: ignore[misc]


def test_worker_rejects_non_semver_versions() -> None:
    with pytest.raises(ValidationError):
        make_worker(graph_version="v1")
    with pytest.raises(ValidationError):
        make_worker(worker_version="1.0")


def test_worker_rejects_unknown_domain_and_autonomy() -> None:
    with pytest.raises(ValidationError):
        make_worker(domain="super_agent")
    with pytest.raises(ValidationError):
        make_worker(autonomy_level="A9")


def test_tool_name_must_be_namespaced() -> None:
    with pytest.raises(ValidationError):
        make_tool(name="prepare")


def test_critical_side_effect_always_requires_approval() -> None:
    tool = make_tool(side_effect_level="critical", approval_policy="never")
    assert tool.requires_approval()
    assert make_tool(approval_policy="always").requires_approval()
    assert not make_tool().requires_approval()


def test_tool_timeout_and_retry_bounds() -> None:
    with pytest.raises(ValidationError):
        make_tool(timeout_seconds=0)
    with pytest.raises(ValidationError):
        make_tool(max_retries=99)


def test_run_context_defaults_to_vietnamese_locale() -> None:
    ctx = RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="tender",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=frozenset({"tender.read"}),
        trace_id="trace-123",
    )
    assert ctx.locale == "vi-VN"
