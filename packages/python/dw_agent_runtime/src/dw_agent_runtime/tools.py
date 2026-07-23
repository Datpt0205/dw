"""Tool registry: versioned tool definitions bound to typed handlers (§7.6)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.registry import ConfigError
from dw_kernel.errors import NotFoundError

ToolHandler = Callable[[BaseModel, RunContext], Awaitable[BaseModel]]


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler


@dataclass
class ToolRegistry:
    """Fail-fast registry keyed by (name, version)."""

    _tools: dict[tuple[str, str], RegisteredTool] = field(default_factory=dict)

    def register(self, tool: RegisteredTool) -> None:
        key = (tool.definition.name, tool.definition.version)
        if key in self._tools:
            raise ConfigError(f"tool already registered: {key[0]}@{key[1]}")
        self._tools[key] = tool

    def resolve(self, name: str, version: str) -> RegisteredTool:
        tool = self._tools.get((name, version))
        if tool is None:
            raise NotFoundError(
                "tool version not registered",
                details={"tool": name, "version": version},
            )
        return tool

    def all_definitions(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]
