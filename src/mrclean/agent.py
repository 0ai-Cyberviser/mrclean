from __future__ import annotations

from dataclasses import dataclass

from .config import MrCleanConfig, RepositoryConfig
from .models import ChatMessage, CompletionRequest, ModelClient, StubModelClient
from .policies import PlannedAction, PolicyEngine
from .prompts import MR_CLEAN_SYSTEM_PROMPT


@dataclass(slots=True)
class CleanupSignal:
    repository: RepositoryConfig
    goal: str
    branch: str
    failing_checks: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    notes: str = ""


@dataclass(slots=True)
class AgentPlan:
    repository: str
    goal: str
    model_summary: str
    actions: tuple[PlannedAction, ...]
    policy_notes: tuple[str, ...]


class MrCleanAgent:
    def __init__(self, config: MrCleanConfig, model_client: ModelClient | None = None) -> None:
        self.config = config
        self.model_client = model_client or StubModelClient()
        self.policy = PolicyEngine(config.policy)

    def draft_plan(self, signal: CleanupSignal) -> AgentPlan:
        model_summary = self.model_client.complete(
            CompletionRequest(
                model=self.config.model.name,
                temperature=self.config.model.temperature,
                max_tokens=self.config.model.max_tokens,
                messages=(
                    ChatMessage(role="system", content=MR_CLEAN_SYSTEM_PROMPT),
                    ChatMessage(
                        role="user",
                        content=self._render_signal(signal),
                    ),
                ),
            )
        ).content

        actions = self._build_actions(signal)
        policy_notes = tuple(
            f"{action.kind}: {self.policy.review(action).reason}" for action in actions
        )
        return AgentPlan(
            repository=signal.repository.name,
            goal=signal.goal,
            model_summary=model_summary,
            actions=actions,
            policy_notes=policy_notes,
        )

    def _build_actions(self, signal: CleanupSignal) -> tuple[PlannedAction, ...]:
        actions: list[PlannedAction] = [
            PlannedAction(
                kind="inspect_signal",
                repository=signal.repository.name,
                branch=signal.branch,
                summary="Inspect current checks, review context, and recent branch diff.",
            )
        ]

        if signal.failing_checks:
            actions.append(
                PlannedAction(
                    kind="edit_patch",
                    repository=signal.repository.name,
                    branch=signal.branch,
                    summary=f"Patch the narrowest cause of failing checks: {', '.join(signal.failing_checks)}.",
                    file_count=max(1, min(len(signal.changed_files) or 1, 3)),
                )
            )
            actions.append(
                PlannedAction(
                    kind="push_commit",
                    repository=signal.repository.name,
                    branch=signal.branch,
                    summary="Push a validated fix after local verification.",
                    file_count=max(1, min(len(signal.changed_files) or 1, 3)),
                )
            )
        else:
            actions.append(
                PlannedAction(
                    kind="review_pr_scope",
                    repository=signal.repository.name,
                    branch=signal.branch,
                    summary="Review branch scope and check whether older PRs are superseded.",
                    file_count=0,
                )
            )

        if "stale" in signal.goal.lower():
            actions.append(
                PlannedAction(
                    kind="close_pr",
                    repository=signal.repository.name,
                    branch=signal.branch,
                    summary="Close stale or superseded PRs after confirming replacements exist.",
                    risky=True,
                )
            )

        return tuple(actions)

    def _render_signal(self, signal: CleanupSignal) -> str:
        checks = ", ".join(signal.failing_checks) if signal.failing_checks else "none"
        files = ", ".join(signal.changed_files) if signal.changed_files else "none"
        return (
            f"Repository: {signal.repository.name}\n"
            f"Branch: {signal.branch}\n"
            f"Goal: {signal.goal}\n"
            f"Failing checks: {checks}\n"
            f"Changed files: {files}\n"
            f"Notes: {signal.notes or 'none'}"
        )

