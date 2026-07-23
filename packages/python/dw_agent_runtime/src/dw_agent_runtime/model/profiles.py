"""Model profile configuration (blueprint §18.3): routing + budgets per profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dw_agent_runtime.registry import ConfigError
from dw_kernel.errors import NotFoundError


class ModelRoute(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    timeout_seconds: int = Field(default=60, gt=0, le=600)


class ModelBudgets(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_input_tokens_per_run: int = Field(default=120_000, gt=0)
    max_cost_usd_per_run: float = Field(default=2.0, gt=0)


class ModelProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(pattern=r"^1\.0$")
    profile_id: str
    routing_policy_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    structured_extraction: ModelRoute
    reasoning: ModelRoute
    fallback: ModelRoute | None = None
    budgets: ModelBudgets = ModelBudgets()


@dataclass
class ModelProfileRegistry:
    _profiles: dict[str, ModelProfile] = field(default_factory=dict)

    def load_directory(self, directory: Path) -> None:
        for path in sorted(directory.glob("*.yaml")):
            self.load_file(path)

    def load_file(self, path: Path) -> ModelProfile:
        try:
            profile = ModelProfile.model_validate(yaml.safe_load(path.read_bytes()))
        except (yaml.YAMLError, ValidationError) as exc:
            raise ConfigError(f"model profile {path.name} invalid: {exc}") from exc
        self.register(profile)
        return profile

    def register(self, profile: ModelProfile) -> None:
        if profile.profile_id in self._profiles:
            raise ConfigError(f"model profile already registered: {profile.profile_id}")
        self._profiles[profile.profile_id] = profile

    def resolve(self, profile_id: str) -> ModelProfile:
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise NotFoundError("model profile not registered", details={"profile_id": profile_id})
        return profile
