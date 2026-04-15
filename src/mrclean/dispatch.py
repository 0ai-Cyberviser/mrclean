from __future__ import annotations

from dataclasses import dataclass

from .monitor import ScanResult
from .policies import PolicyEngine


@dataclass(slots=True)
class DispatchAction:
    kind: str
    summary: str
    allowed: bool
    reason: str
    command_hint: str = ""


@dataclass(slots=True)
class DispatchCandidate:
    repository: str
    number: int
    title: str
    url: str
    branch: str
    category: str
    status: str
    priority: int
    workspace_ready: bool
    workspace_reason: str
    changed_files: tuple[str, ...]
    actions: tuple[DispatchAction, ...]
    assessment_outcome: str = "unknown"
    assessment_false_positive_risk: str = "unknown"
    assessment_runtime_risk: str = "unknown"
    assessment_confidence: int = 0
    assessment_recommended_action: str = ""


class DispatchPlanner:
    def __init__(self, policy: PolicyEngine) -> None:
        self.policy = policy

    def build(self, results: tuple[ScanResult, ...]) -> tuple[DispatchCandidate, ...]:
        candidates = [self._build_candidate(item) for item in results]
        candidates.sort(key=lambda item: (item.priority, _status_rank(item.status), item.repository.lower(), item.number))
        return tuple(candidates)

    def _build_candidate(self, item: ScanResult) -> DispatchCandidate:
        workspace_ready, workspace_reason = _workspace_state(item)
        if item.plan is None:
            return DispatchCandidate(
                repository=item.repository,
                number=item.number,
                title=item.title,
                url=item.url,
                branch=item.branch,
                category=item.category,
                status="deferred",
                priority=_priority(item.category),
                workspace_ready=workspace_ready,
                workspace_reason=workspace_reason,
                changed_files=item.changed_files,
                actions=(),
            )

        actions: list[DispatchAction] = []
        for planned in item.plan.actions:
            policy_result = self.policy.review(planned)
            allowed = policy_result.allowed
            reason = policy_result.reason

            if planned.kind in {"edit_patch", "push_commit"} and not workspace_ready:
                allowed = False
                reason = workspace_reason or "local workspace is not ready for this PR branch"

            actions.append(
                DispatchAction(
                    kind=planned.kind,
                    summary=planned.summary,
                    allowed=allowed,
                    reason=reason,
                    command_hint=_command_hint(item, planned.kind),
                )
            )

        return DispatchCandidate(
            repository=item.repository,
            number=item.number,
            title=item.title,
            url=item.url,
            branch=item.branch,
            category=item.category,
            status=_candidate_status(item, actions),
            priority=_priority(item.category),
            workspace_ready=workspace_ready,
            workspace_reason=workspace_reason,
            changed_files=item.changed_files,
            actions=tuple(actions),
        )


def _priority(category: str) -> int:
    order = {
        "needs_attention": 0,
        "superseded_candidate": 1,
        "pending": 2,
        "healthy": 3,
    }
    return order.get(category, 9)


def _status_rank(status: str) -> int:
    order = {
        "ready": 0,
        "inspect_only": 1,
        "deferred": 2,
        "blocked": 3,
    }
    return order.get(status, 9)


def _workspace_state(item: ScanResult) -> tuple[bool, str]:
    if not item.workspace_path:
        return False, "no local workspace configured"
    if item.workspace_notes:
        return False, "; ".join(item.workspace_notes)
    return True, "workspace matches PR branch"


def _candidate_status(item: ScanResult, actions: list[DispatchAction]) -> str:
    if item.category == "pending":
        return "deferred"

    interesting = [action for action in actions if action.kind != "inspect_signal"]
    if any(action.allowed for action in interesting):
        return "ready"
    if any(action.allowed for action in actions):
        return "inspect_only"
    return "blocked"


def _command_hint(item: ScanResult, kind: str) -> str:
    if kind == "inspect_signal":
        return f"gh pr view {item.number} --repo {item.repository} --comments"
    if kind == "review_pr_scope":
        return f"gh pr view {item.number} --repo {item.repository}"
    if kind == "edit_patch" and item.workspace_path:
        return f"git -C {item.workspace_path} status --short && git -C {item.workspace_path} diff --stat"
    if kind == "push_commit" and item.workspace_path:
        return f"git -C {item.workspace_path} push origin {item.branch}"
    if kind == "close_pr":
        return f"gh pr close {item.number} --repo {item.repository}"
    return ""
