from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath

from .config import MrCleanConfig
from .dispatch import DispatchCandidate
from .models import ChatMessage, CompletionRequest, ModelClient, build_model_client
from .prompts import MR_CLEAN_INTENT_PROMPT
from .runner import RunSession


@dataclass(slots=True)
class IntentEdit:
    path: str
    operation: str
    summary: str
    reason: str


@dataclass(slots=True)
class EditIntent:
    repository: str
    number: int
    branch: str
    candidate_status: str
    run_status: str
    summary: str
    edits: tuple[IntentEdit, ...]
    validation: tuple[str, ...]
    risks: tuple[str, ...]
    model_provider: str
    model_name: str
    raw: dict[str, object]


class IntentValidationError(ValueError):
    """Raised when a generated intent is structurally invalid."""


class IntentGenerator:
    def __init__(self, config: MrCleanConfig, model_client: ModelClient | None = None) -> None:
        self.config = config
        self.model_client = model_client or build_model_client(config.model.provider, config.model.name)

    def generate(self, candidate: DispatchCandidate, session: RunSession) -> EditIntent:
        response = self.model_client.complete(
            CompletionRequest(
                model=self.config.model.name,
                temperature=self.config.model.temperature,
                max_tokens=self.config.model.max_tokens,
                messages=(
                    ChatMessage(role="system", content=MR_CLEAN_INTENT_PROMPT),
                    ChatMessage(role="user", content=_render_intent_context(candidate, session)),
                ),
            )
        )
        payload = _parse_intent_payload(response.content)
        edits = tuple(_parse_edit(entry) for entry in payload.get("edits", []))
        _validate_intent(edits, self.config)

        provider = str(response.raw.get("provider", "stub"))
        model_name = str(response.raw.get("model", self.config.model.name))
        return EditIntent(
            repository=candidate.repository,
            number=candidate.number,
            branch=candidate.branch,
            candidate_status=candidate.status,
            run_status=session.run_status,
            summary=str(payload["summary"]).strip(),
            edits=edits,
            validation=tuple(_string_list(payload.get("validation", []), field_name="validation")),
            risks=tuple(_string_list(payload.get("risks", []), field_name="risks")),
            model_provider=provider,
            model_name=model_name,
            raw=response.raw,
        )


def _render_intent_context(candidate: DispatchCandidate, session: RunSession) -> str:
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


def _parse_intent_payload(content: str) -> dict[str, object]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise IntentValidationError(f"intent response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise IntentValidationError("intent response must be a JSON object")
    if not isinstance(payload.get("summary"), str) or not str(payload["summary"]).strip():
        raise IntentValidationError("intent summary must be a non-empty string")
    return payload


def _parse_edit(entry: object) -> IntentEdit:
    if not isinstance(entry, dict):
        raise IntentValidationError("each edit entry must be an object")
    path = _require_non_empty_string(entry, "path")
    operation = _require_non_empty_string(entry, "operation")
    summary = _require_non_empty_string(entry, "summary")
    reason = _require_non_empty_string(entry, "reason")
    if operation not in {"modify", "create", "delete"}:
        raise IntentValidationError(f"unsupported edit operation: {operation!r}")
    _validate_relative_path(path)
    return IntentEdit(path=path, operation=operation, summary=summary, reason=reason)


def _validate_intent(edits: tuple[IntentEdit, ...], config: MrCleanConfig) -> None:
    if not edits:
        raise IntentValidationError("intent must include at least one edit")
    if len(edits) > config.policy.max_patch_files:
        raise IntentValidationError(
            f"intent includes {len(edits)} edits, exceeding policy.max_patch_files={config.policy.max_patch_files}"
        )
    paths = [edit.path for edit in edits]
    if len(paths) != len(set(paths)):
        raise IntentValidationError("intent edit paths must be unique")


def _require_non_empty_string(entry: dict[str, object], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntentValidationError(f"intent field {key!r} must be a non-empty string")
    return value.strip()


def _string_list(value: object, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise IntentValidationError(f"intent field {field_name!r} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise IntentValidationError(f"intent field {field_name!r} must contain only non-empty strings")
        result.append(item.strip())
    return result


def _validate_relative_path(path: str) -> None:
    normalized = PurePosixPath(path)
    if normalized.is_absolute():
        raise IntentValidationError(f"intent path must be relative: {path!r}")
    if ".." in normalized.parts:
        raise IntentValidationError(f"intent path must not escape the repository: {path!r}")
