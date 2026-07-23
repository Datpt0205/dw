from pathlib import Path

import pytest

from dw_agent_runtime.registry import ConfigError, GraphRegistry, WorkerRegistry
from dw_agent_runtime.testing.demo_graph import DEMO_WORKER_YAML, build_demo_graph
from dw_kernel.errors import NotFoundError

pytestmark = pytest.mark.unit


def make_registries() -> tuple[GraphRegistry, WorkerRegistry]:
    graphs = GraphRegistry()
    graphs.register("demo_approval", "1.0.0", build_demo_graph)
    return graphs, WorkerRegistry(graph_registry=graphs)


def test_graph_registry_fail_fast() -> None:
    graphs = GraphRegistry()
    graphs.register("demo_approval", "1.0.0", build_demo_graph)
    with pytest.raises(ConfigError, match="already registered"):
        graphs.register("demo_approval", "1.0.0", build_demo_graph)
    with pytest.raises(NotFoundError):
        graphs.resolve("demo_approval", "9.9.9")


def test_worker_registry_loads_valid_yaml(tmp_path: Path) -> None:
    _, workers = make_registries()
    config = tmp_path / "demo_approval.yaml"
    config.write_text(DEMO_WORKER_YAML, encoding="utf-8")
    loaded = workers.load_file(config)
    assert loaded.definition.worker_id == "demo_approval"
    assert loaded.definition.autonomy_level == "A2"
    assert len(loaded.checksum) == 64
    assert workers.resolve("demo_approval", "1.0.0").checksum == loaded.checksum


def test_worker_registry_rejects_unknown_schema_version(tmp_path: Path) -> None:
    _, workers = make_registries()
    config = tmp_path / "bad.yaml"
    config.write_text(DEMO_WORKER_YAML.replace('"1.0"', '"9.9"'), encoding="utf-8")
    with pytest.raises(ConfigError, match="schema_version"):
        workers.load_file(config)


def test_worker_registry_rejects_bad_semver(tmp_path: Path) -> None:
    _, workers = make_registries()
    config = tmp_path / "bad.yaml"
    config.write_text(
        DEMO_WORKER_YAML.replace('worker_version: "1.0.0"', 'worker_version: "v1"'),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="invalid"):
        workers.load_file(config)


def test_worker_registry_rejects_unregistered_graph(tmp_path: Path) -> None:
    _, workers = make_registries()
    config = tmp_path / "bad.yaml"
    config.write_text(
        DEMO_WORKER_YAML.replace('graph_version: "1.0.0"', 'graph_version: "2.0.0"'),
        encoding="utf-8",
    )
    with pytest.raises(NotFoundError, match="graph version"):
        workers.load_file(config)


def test_worker_registry_rejects_duplicates(tmp_path: Path) -> None:
    _, workers = make_registries()
    config = tmp_path / "demo_approval.yaml"
    config.write_text(DEMO_WORKER_YAML, encoding="utf-8")
    workers.load_file(config)
    with pytest.raises(ConfigError, match="already registered"):
        workers.load_file(config)
