from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .config import MrCleanConfig
from .materialize import MaterializedEdit, MaterializedIntent
from .models import ChatMessage, CompletionRequest, ModelClient, build_model_client
from .prompts import MR_CLEAN_DRAFT_PROMPT


@dataclass(slots=True)
class DraftOperation:
    path: str
    requested_operation: str
    action: str
    summary: str
    reason: str
    absolute_path: str
    status: str
    validation_reason: str
    expected_sha256: str
    content_sha256: str = ""
    content_bytes: int | None = None
    content_preview: str = ""
    content: str = ""


@dataclass(slots=True)
class DraftBundle:
    repository: str
    number: int
    branch: str
    status: str
    summary: str
    operations: tuple[DraftOperation, ...]
    validation: tuple[str, ...]
    risks: tuple[str, ...]
    model_provider: str
    model_name: str
    raw: dict[str, object]


class DraftValidationError(ValueError):
    """Raised when a generated draft bundle is structurally invalid."""


class DraftGenerator:
    def __init__(
        self,
        config: MrCleanConfig,
        model_client: ModelClient | None = None,
        *,
        max_input_chars: int = 20000,
        preview_chars: int = 500,
    ) -> None:
        self.config = config
        self.model_client = model_client or build_model_client(config.model.provider, config.model.name)
        self.max_input_chars = max_input_chars
        self.preview_chars = preview_chars

    def generate(self, materialized: MaterializedIntent) -> DraftBundle:
        if materialized.status != "ready":
            return _blocked_bundle(
                materialized,
                {
                    edit.path: edit.validation_reason or "materialized edit is not ready"
                    for edit in materialized.edits
                },
                reason="draft generation skipped because the materialized intent is not ready",
            )

        prepared, blocked = self._prepare_inputs(materialized)
        if blocked:
            return _blocked_bundle(
                materialized,
                blocked,
                reason="draft generation skipped because one or more edit targets could not be prepared",
            )

        response = self.model_client.complete(
            CompletionRequest(
                model=self.config.model.name,
                temperature=self.config.model.temperature,
                max_tokens=self.config.model.max_tokens,
                messages=(
                    ChatMessage(role="system", content=MR_CLEAN_DRAFT_PROMPT),
                    ChatMessage(role="user", content=_render_draft_context(materialized, prepared)),
                ),
            )
        )
        payload = _parse_draft_payload(response.content)
        operations = _parse_operations(
            payload.get("operations", []),
            materialized,
            prepared,
            preview_chars=self.preview_chars,
        )
        status = "ready" if all(operation.status == "ready" for operation in operations) else "blocked"
        return DraftBundle(
            repository=materialized.repository,
            number=materialized.number,
            branch=materialized.branch,
            status=status,
            summary=str(payload["summary"]).strip(),
            operations=operations,
            validation=tuple(_string_list(payload.get("validation", []), field_name="validation")),
            risks=tuple(_string_list(payload.get("risks", []), field_name="risks")),
            model_provider=str(response.raw.get("provider", "stub")),
            model_name=str(response.raw.get("model", self.config.model.name)),
            raw=response.raw,
        )

    def _prepare_inputs(self, materialized: MaterializedIntent) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
        prepared: dict[str, dict[str, object]] = {}
        blocked: dict[str, str] = {}
        for edit in materialized.edits:
            entry = {
                "path": edit.path,
                "operation": edit.operation,
                "summary": edit.summary,
                "reason": edit.reason,
                "absolute_path": edit.absolute_path,
                "expected_sha256": edit.sha256,
                "current_preview": edit.preview,
            }
            if edit.operation == "modify":
                try:
                    content = Path(edit.absolute_path).read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    blocked[edit.path] = "current file is not UTF-8 text"
                    continue
                if len(content) > self.max_input_chars:
                    blocked[edit.path] = (
                        f"current file exceeds max_input_chars={self.max_input_chars}"
                    )
                    continue
                entry["current_content"] = content
            prepared[edit.path] = entry
        return prepared, blocked


def _render_draft_context(
    materialized: MaterializedIntent,
    prepared: dict[str, dict[str, object]],
) -> str:
    payload = {
        "repository": materialized.repository,
        "number": materialized.number,
        "branch": materialized.branch,
        "summary": materialized.summary,
        "validation": list(materialized.validation),
        "risks": list(materialized.risks),
        "edits": [prepared[edit.path] for edit in materialized.edits if edit.path in prepared],
    }
    return json.dumps(payload, indent=2)


def _parse_draft_payload(content: str) -> dict[str, object]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise DraftValidationError(f"draft response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DraftValidationError("draft response must be a JSON object")
    if not isinstance(payload.get("summary"), str) or not str(payload["summary"]).strip():
        raise DraftValidationError("draft summary must be a non-empty string")
    return payload


def _parse_operations(
    operations: object,
    materialized: MaterializedIntent,
    prepared: dict[str, dict[str, object]],
    *,
    preview_chars: int,
) -> tuple[DraftOperation, ...]:
    if not isinstance(operations, list):
        raise DraftValidationError("draft operations must be a list")

    expected = {edit.path: edit for edit in materialized.edits}
    seen: set[str] = set()
    parsed: list[DraftOperation] = []
    for entry in operations:
        if not isinstance(entry, dict):
            raise DraftValidationError("each draft operation must be an object")

        path = _require_non_empty_string(entry, "path")
        if path in seen:
            raise DraftValidationError(f"draft operation path is duplicated: {path!r}")
        seen.add(path)

        edit = expected.get(path)
        if edit is None:
            raise DraftValidationError(f"draft operation path is not part of the materialized intent: {path!r}")

        action = _require_non_empty_string(entry, "action")
        summary = _require_non_empty_string(entry, "summary")
        reason = _require_non_empty_string(entry, "reason")

        expected_action = _expected_action(edit.operation)
        problems: list[str] = []
        if action != expected_action:
            problems.append(f"expected action {expected_action!r}, received {action!r}")

        content = ""
        content_sha256 = ""
        content_bytes: int | None = None
        content_preview = ""
        if action == "write_file":
            content = _require_non_empty_string(entry, "content")
            encoded = content.encode("utf-8")
            content_sha256 = hashlib.sha256(encoded).hexdigest()
            content_bytes = len(encoded)
            content_preview = content[:preview_chars]
            if edit.operation == "modify":
                current_content = str(prepared[path].get("current_content", ""))
                if content == current_content:
                    problems.append("draft content does not change the current file")
        elif action != "delete_file":
            problems.append(f"unsupported draft action: {action!r}")

        parsed.append(
            DraftOperation(
                path=path,
                requested_operation=edit.operation,
                action=action,
                summary=summary,
                reason=reason,
                absolute_path=edit.absolute_path,
                status="blocked" if problems else "ready",
                validation_reason="; ".join(problems) if problems else "ready",
                expected_sha256=edit.sha256,
                content_sha256=content_sha256,
                content_bytes=content_bytes,
                content_preview=content_preview,
                content=content,
            )
        )

    missing = tuple(path for path in expected if path not in seen)
    if missing:
        raise DraftValidationError(f"draft omitted materialized paths: {', '.join(missing)}")
    return tuple(parsed)


def _blocked_bundle(
    materialized: MaterializedIntent,
    blocked: dict[str, str],
    *,
    reason: str,
) -> DraftBundle:
    operations = tuple(
        DraftOperation(
            path=edit.path,
            requested_operation=edit.operation,
            action=_expected_action(edit.operation),
            summary=edit.summary,
            reason=edit.reason,
            absolute_path=edit.absolute_path,
            status="blocked",
            validation_reason=blocked.get(edit.path, reason),
            expected_sha256=edit.sha256,
        )
        for edit in materialized.edits
    )
    risks = materialized.risks + (reason,)
    return DraftBundle(
        repository=materialized.repository,
        number=materialized.number,
        branch=materialized.branch,
        status="blocked",
        summary="Draft generation is blocked until the materialized intent is ready and readable.",
        operations=operations,
        validation=materialized.validation,
        risks=risks,
        model_provider="skipped",
        model_name="",
        raw={"provider": "skipped", "reason": reason},
    )


def _expected_action(operation: str) -> str:
    if operation == "delete":
        return "delete_file"
    return "write_file"


def _require_non_empty_string(entry: dict[str, object], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DraftValidationError(f"draft field {key!r} must be a non-empty string")
    return value.strip()


def _string_list(value: object, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DraftValidationError(f"draft field {field_name!r} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise DraftValidationError(f"draft field {field_name!r} must contain only non-empty strings")
        result.append(item.strip())
    return result
