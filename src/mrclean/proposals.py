from __future__ import annotations

from dataclasses import dataclass

from .config import MrCleanConfig
from .dispatch import DispatchCandidate
from .models import ChatMessage, CompletionResponse, CompletionRequest, ModelClient, StubModelClient, build_model_client
from .prompts import MR_CLEAN_PROPOSAL_PROMPT
from .runner import RunSession


@dataclass(slots=True)
class Proposal:
    repository: str
    number: int
    branch: str
    candidate_status: str
    run_status: str
    content: str
    model_provider: str
    model_name: str
    raw: dict[str, object]


class ProposalGenerator:
    def __init__(self, config: MrCleanConfig, model_client: ModelClient | None = None) -> None:
        self.config = config
        self.model_client = model_client or build_model_client(config.model.provider, config.model.name)

    def generate(self, candidate: DispatchCandidate, session: RunSession) -> Proposal:
        response = self.model_client.complete(
            CompletionRequest(
                model=self.config.model.name,
                temperature=self.config.model.temperature,
                max_tokens=self.config.model.max_tokens,
                messages=(
                    ChatMessage(role="system", content=MR_CLEAN_PROPOSAL_PROMPT),
                    ChatMessage(role="user", content=_render_proposal_context(candidate, session)),
                ),
            )
        )
        provider = str(response.raw.get("provider", "stub"))
        model_name = str(response.raw.get("model", self.config.model.name))
        return Proposal(
            repository=candidate.repository,
            number=candidate.number,
            branch=candidate.branch,
            candidate_status=candidate.status,
            run_status=session.run_status,
            content=response.content,
            model_provider=provider,
            model_name=model_name,
            raw=response.raw,
        )


def _render_proposal_context(candidate: DispatchCandidate, session: RunSession) -> str:
    lines = [
        f"Repository: {candidate.repository}",
        f"PR: #{candidate.number}",
        f"Title: {candidate.title}",
        f"Branch: {candidate.branch}",
        f"Category: {candidate.category}",
        f"Candidate status: {candidate.status}",
        f"Run status: {session.run_status}",
        f"Workspace ready: {'yes' if candidate.workspace_ready else 'no'}",
        f"Workspace reason: {candidate.workspace_reason}",
        f"Changed files: {', '.join(candidate.changed_files) if candidate.changed_files else 'none'}",
        "Actions:",
    ]
    for action in candidate.actions:
        verdict = "allowed" if action.allowed else "blocked"
        lines.append(f"- {action.kind} [{verdict}]: {action.summary}")
        lines.append(f"  reason: {action.reason}")

    lines.append("Safe command outputs:")
    if not session.executions:
        lines.append("- none")
    for execution in session.executions:
        lines.append(f"- {execution.kind} [{execution.status}]")
        lines.append(f"  reason: {execution.reason}")
        if execution.command:
            lines.append(f"  command: {execution.command}")
        if execution.stdout.strip():
            lines.append("  stdout:")
            for line in execution.stdout.rstrip().splitlines():
                lines.append(f"    {line}")
        if execution.stderr.strip():
            lines.append("  stderr:")
            for line in execution.stderr.rstrip().splitlines():
                lines.append(f"    {line}")
    return "\n".join(lines)
