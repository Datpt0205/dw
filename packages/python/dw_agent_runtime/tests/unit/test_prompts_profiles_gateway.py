import uuid
from pathlib import Path

import pytest
from pydantic import BaseModel

from dw_agent_runtime.adapters.mock_model import MockModelAdapter
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder, RoutingModelGateway
from dw_agent_runtime.model.profiles import ModelProfileRegistry
from dw_agent_runtime.model.prompts import PromptArtifact, PromptRegistry
from dw_agent_runtime.ports import ModelRequest
from dw_agent_runtime.registry import ConfigError
from dw_kernel.errors import DomainError, NotFoundError

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]


def make_run_context() -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="demo_approval",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=frozenset({"work_ops.read"}),
        trace_id="trace-1",
    )


def make_prompt(**overrides: object) -> PromptArtifact:
    defaults: dict[str, object] = {
        "schema_version": "1.0",
        "prompt_id": "demo.summarize",
        "version": "1.0.0",
        "system": "Bạn là trợ lý tóm tắt.",
        "template": "Tóm tắt nội dung: {content}",
        "variables": frozenset({"content"}),
    }
    defaults.update(overrides)
    return PromptArtifact.model_validate(defaults)


class SummaryOutput(BaseModel):
    summary: str
    language: str


def test_prompt_render_strict_variables() -> None:
    registry = PromptRegistry()
    registry.register(make_prompt())
    rendered = registry.render("demo.summarize", "1.0.0", {"content": "cuộc họp tuần"})
    assert "cuộc họp tuần" in rendered.user
    with pytest.raises(DomainError, match="variables mismatch"):
        registry.render("demo.summarize", "1.0.0", {})
    with pytest.raises(DomainError, match="variables mismatch"):
        registry.render("demo.summarize", "1.0.0", {"content": "x", "extra": "y"})
    with pytest.raises(NotFoundError):
        registry.render("demo.summarize", "2.0.0", {"content": "x"})


def test_prompt_duplicate_rejected() -> None:
    registry = PromptRegistry()
    registry.register(make_prompt())
    with pytest.raises(ConfigError, match="already registered"):
        registry.register(make_prompt())


def test_model_profiles_load_from_repo_configs() -> None:
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    balanced = profiles.resolve("balanced")
    assert balanced.structured_extraction.provider == "mock"
    assert balanced.budgets.max_cost_usd_per_run == 2.0
    with pytest.raises(NotFoundError):
        profiles.resolve("premium")


def make_gateway(adapter: MockModelAdapter) -> RoutingModelGateway:
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    prompts = PromptRegistry()
    prompts.register(make_prompt())
    return RoutingModelGateway(
        profiles=profiles,
        prompts=prompts,
        adapters={"mock": adapter},
        usage_recorder=InMemoryUsageRecorder(),
    )


async def test_gateway_returns_validated_output_and_records_usage() -> None:
    adapter = MockModelAdapter()
    adapter.register_builder(
        "demo.summarize",
        "1.0.0",
        lambda prompt: {"summary": "Ba quyết định chính.", "language": "vi"},
    )
    gateway = make_gateway(adapter)
    recorder = gateway.usage_recorder
    assert isinstance(recorder, InMemoryUsageRecorder)

    request = ModelRequest(
        task="structured_extraction",
        prompt_id="demo.summarize",
        prompt_version="1.0.0",
        variables={"content": "họp giao ban"},
        model_profile="balanced",
    )
    output = await gateway.generate_structured(
        request, SummaryOutput, run_context=make_run_context()
    )
    assert output.language == "vi"
    assert len(adapter.calls) == 1
    assert recorder.records[0][1].provider == "mock"


async def test_gateway_rejects_schema_invalid_mock_response() -> None:
    adapter = MockModelAdapter()
    adapter.register_builder("demo.summarize", "1.0.0", lambda prompt: {"wrong_field": True})
    gateway = make_gateway(adapter)
    request = ModelRequest(
        task="structured_extraction",
        prompt_id="demo.summarize",
        prompt_version="1.0.0",
        variables={"content": "x"},
    )
    with pytest.raises(DomainError, match="schema validation"):
        await gateway.generate_structured(request, SummaryOutput, run_context=make_run_context())


async def test_gateway_unknown_provider_fails_fast() -> None:
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    prompts = PromptRegistry()
    prompts.register(make_prompt())
    gateway = RoutingModelGateway(
        profiles=profiles, prompts=prompts, adapters={}, usage_recorder=InMemoryUsageRecorder()
    )
    request = ModelRequest(
        task="reasoning",
        prompt_id="demo.summarize",
        prompt_version="1.0.0",
        variables={"content": "x"},
    )
    with pytest.raises(NotFoundError, match="provider"):
        await gateway.generate_structured(request, SummaryOutput, run_context=make_run_context())


def test_extract_json_object_tolerates_fences_and_preamble() -> None:
    from dw_agent_runtime.adapters.openai_compatible import _extract_json_object

    assert _extract_json_object('{"a": 1}') == {"a": 1}
    assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json_object('Kết quả:\n{"a": {"b": 2}} xong') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        _extract_json_object("no json here")
    with pytest.raises(ValueError):
        _extract_json_object("[1, 2]")
