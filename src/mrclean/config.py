from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(slots=True)
class ModelConfig:
    provider: str
    name: str
    temperature: float = 0.1
    max_tokens: int = 4096


@dataclass(slots=True)
class PolicyConfig:
    dry_run: bool = True
    allow_push: bool = False
    allow_close_stale_prs: bool = False
    allow_force_push: bool = False
    max_patch_files: int = 5
    protected_branches: tuple[str, ...] = ("main", "master")


@dataclass(slots=True)
class RepositoryConfig:
    name: str
    base_branch: str = "main"
    local_path: str | None = None
    labels: tuple[str, ...] = ()
    monitored_checks: tuple[str, ...] = ()


@dataclass(slots=True)
class MrCleanConfig:
    name: str
    model: ModelConfig
    policy: PolicyConfig
    repositories: tuple[RepositoryConfig, ...]

    @classmethod
    def from_toml(cls, path: str | Path) -> "MrCleanConfig":
        config_path = Path(path)
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)

        model_section = raw.get("model", {})
        policy_section = raw.get("policy", {})
        repository_sections = raw.get("repositories", [])

        model = ModelConfig(
            provider=_require_string(model_section, "provider"),
            name=_require_string(model_section, "name"),
            temperature=float(model_section.get("temperature", 0.1)),
            max_tokens=int(model_section.get("max_tokens", 4096)),
        )

        policy = PolicyConfig(
            dry_run=bool(policy_section.get("dry_run", True)),
            allow_push=bool(policy_section.get("allow_push", False)),
            allow_close_stale_prs=bool(policy_section.get("allow_close_stale_prs", False)),
            allow_force_push=bool(policy_section.get("allow_force_push", False)),
            max_patch_files=int(policy_section.get("max_patch_files", 5)),
            protected_branches=tuple(policy_section.get("protected_branches", ("main", "master"))),
        )

        if policy.max_patch_files < 1:
            raise ValueError("policy.max_patch_files must be >= 1")
        if policy.allow_force_push and not policy.allow_push:
            raise ValueError("policy.allow_force_push requires policy.allow_push")

        repositories = tuple(_parse_repository(item) for item in repository_sections)
        if not repositories:
            raise ValueError("at least one [[repositories]] entry is required")

        return cls(
            name=str(raw.get("name", "mrclean")),
            model=model,
            policy=policy,
            repositories=repositories,
        )

    def get_repository(self, name: str) -> RepositoryConfig:
        for repository in self.repositories:
            if repository.name == name:
                return repository
        raise KeyError(f"repository not found: {name}")


def sample_config() -> str:
    return """name = "mrclean"

[model]
provider = "openai"
name = "gpt-5.4-mini"
temperature = 0.1
max_tokens = 4096

[policy]
dry_run = true
allow_push = false
allow_close_stale_prs = false
allow_force_push = false
max_patch_files = 5
protected_branches = ["main", "master"]

[[repositories]]
name = "0ai-Cyberviser/Hancock"
base_branch = "main"
local_path = "/home/oai/Hancock"
labels = ["codex"]
monitored_checks = ["build-linux", "oss-fuzz", "cifuzz", "fuzzing"]

[[repositories]]
name = "0ai-Cyberviser/CyberViser-ViserHub"
base_branch = "main"
local_path = "/home/oai/pr-audits/CyberViser-ViserHub"
labels = ["copilot"]
monitored_checks = ["fuzz-pr", "build-linux"]
"""


def _require_string(section: dict[str, object], key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing or invalid string for {key}")
    return value


def _parse_repository(raw: dict[str, object]) -> RepositoryConfig:
    labels = tuple(raw.get("labels", ()))
    monitored_checks = tuple(raw.get("monitored_checks", ()))
    return RepositoryConfig(
        name=_require_string(raw, "name"),
        base_branch=str(raw.get("base_branch", "main")),
        local_path=str(raw["local_path"]) if "local_path" in raw else None,
        labels=labels,
        monitored_checks=monitored_checks,
    )
