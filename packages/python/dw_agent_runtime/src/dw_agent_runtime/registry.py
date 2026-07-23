"""Typed, fail-fast registries for workers and workflow graphs (blueprint §7.6).

Worker definitions load from versioned YAML artifacts; a config referencing an
unknown graph or malformed version fails at startup, never at run time.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from dw_agent_runtime.contracts import WorkerDefinition
from dw_kernel.errors import DomainError, NotFoundError

# A graph factory returns an *uncompiled* LangGraph StateGraph-like object; the
# runner adapter compiles it with a checkpointer. Typed as Any at this boundary
# because the engine type must not leak into non-adapter code.
GraphFactory = Callable[[], Any]


class ConfigError(DomainError):
    """A configuration artifact is invalid; startup must fail."""


@dataclass
class GraphRegistry:
    """Maps (worker_id, graph_version) -> graph factory."""

    _factories: dict[tuple[str, str], GraphFactory] = field(default_factory=dict)

    def register(self, worker_id: str, graph_version: str, factory: GraphFactory) -> None:
        key = (worker_id, graph_version)
        if key in self._factories:
            raise ConfigError(f"graph already registered: {worker_id}@{graph_version}")
        self._factories[key] = factory

    def resolve(self, worker_id: str, graph_version: str) -> GraphFactory:
        factory = self._factories.get((worker_id, graph_version))
        if factory is None:
            raise NotFoundError(
                "graph version not registered",
                details={"worker_id": worker_id, "graph_version": graph_version},
            )
        return factory


@dataclass(frozen=True)
class LoadedWorker:
    definition: WorkerDefinition
    checksum: str  # sha256 of the config artifact for the release manifest
    source_path: str


@dataclass
class WorkerRegistry:
    """Loads and validates worker definitions from configs/workers/*.yaml."""

    graph_registry: GraphRegistry
    _workers: dict[tuple[str, str], LoadedWorker] = field(default_factory=dict)

    def load_directory(self, directory: Path) -> list[LoadedWorker]:
        loaded: list[LoadedWorker] = []
        for path in sorted(directory.glob("*.yaml")):
            loaded.append(self.load_file(path))
        return loaded

    def load_file(self, path: Path) -> LoadedWorker:
        raw_bytes = path.read_bytes()
        try:
            data = yaml.safe_load(raw_bytes)
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {path.name}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"worker config {path.name} must be a mapping")

        schema_version = data.pop("schema_version", None)
        if schema_version != "1.0":
            raise ConfigError(
                f"worker config {path.name}: unsupported schema_version {schema_version!r}"
            )
        try:
            definition = WorkerDefinition.model_validate(data)
        except ValidationError as exc:
            raise ConfigError(f"worker config {path.name} invalid: {exc}") from exc

        # Fail fast when the referenced graph is not registered.
        self.graph_registry.resolve(definition.worker_id, definition.graph_version)

        loaded = LoadedWorker(
            definition=definition,
            checksum=hashlib.sha256(raw_bytes).hexdigest(),
            source_path=str(path),
        )
        self.register(loaded)
        return loaded

    def register(self, worker: LoadedWorker) -> None:
        key = (worker.definition.worker_id, worker.definition.worker_version)
        if key in self._workers:
            raise ConfigError(
                f"worker already registered: {key[0]}@{key[1]}",
            )
        self._workers[key] = worker

    def resolve(self, worker_id: str, worker_version: str) -> LoadedWorker:
        worker = self._workers.get((worker_id, worker_version))
        if worker is None:
            raise NotFoundError(
                "worker version not registered",
                details={"worker_id": worker_id, "worker_version": worker_version},
            )
        return worker

    def all_workers(self) -> list[LoadedWorker]:
        return list(self._workers.values())
