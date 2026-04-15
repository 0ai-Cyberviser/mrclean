from __future__ import annotations

from dataclasses import dataclass

from .config import PolicyConfig


class PolicyViolation(ValueError):
    """Raised when an action violates automation policy."""


@dataclass(slots=True)
class PlannedAction:
    kind: str
    repository: str
    branch: str
    summary: str
    file_count: int = 0
    risky: bool = False


@dataclass(slots=True)
class PolicyResult:
    allowed: bool
    reason: str


class PolicyEngine:
    def __init__(self, policy: PolicyConfig) -> None:
        self.policy = policy

    def review(self, action: PlannedAction) -> PolicyResult:
        if action.kind == "force_push" and not self.policy.allow_force_push:
            return PolicyResult(False, "force-push is disabled by policy")

        if action.kind == "apply_patch":
            if not self.policy.allow_local_apply:
                return PolicyResult(False, "local apply is disabled by policy")
            if action.branch in self.policy.protected_branches:
                return PolicyResult(False, f"branch {action.branch!r} is protected")

        if action.kind == "push_commit":
            if not self.policy.allow_push:
                return PolicyResult(False, "push is disabled by policy")
            if action.branch in self.policy.protected_branches:
                return PolicyResult(False, f"branch {action.branch!r} is protected")

        if action.kind == "close_pr" and not self.policy.allow_close_stale_prs:
            return PolicyResult(False, "PR closure is disabled by policy")

        if action.file_count > self.policy.max_patch_files:
            return PolicyResult(
                False,
                f"planned patch touches {action.file_count} files, limit is {self.policy.max_patch_files}",
            )

        if action.risky and self.policy.dry_run:
            return PolicyResult(False, "risky action blocked while dry-run is enabled")

        return PolicyResult(True, "allowed")

    def require(self, action: PlannedAction) -> None:
        result = self.review(action)
        if not result.allowed:
            raise PolicyViolation(result.reason)
