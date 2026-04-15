from __future__ import annotations

from dataclasses import dataclass
import difflib
import hashlib
from pathlib import Path

from .drafts import DraftBundle, DraftOperation


@dataclass(slots=True)
class PreviewOperation:
    path: str
    action: str
    absolute_path: str
    status: str
    validation_reason: str
    expected_sha256: str
    current_sha256: str
    current_exists: bool
    diff: str
    diff_bytes: int


@dataclass(slots=True)
class PreviewBundle:
    repository: str
    number: int
    branch: str
    status: str
    summary: str
    operations: tuple[PreviewOperation, ...]
    validation: tuple[str, ...]
    risks: tuple[str, ...]


class DraftPreviewer:
    def preview(self, draft: DraftBundle) -> PreviewBundle:
        if draft.status != "ready":
            operations = tuple(
                PreviewOperation(
                    path=operation.path,
                    action=operation.action,
                    absolute_path=operation.absolute_path,
                    status="blocked",
                    validation_reason=operation.validation_reason or "draft bundle is not ready",
                    expected_sha256=operation.expected_sha256,
                    current_sha256="",
                    current_exists=False,
                    diff="",
                    diff_bytes=0,
                )
                for operation in draft.operations
            )
            return PreviewBundle(
                repository=draft.repository,
                number=draft.number,
                branch=draft.branch,
                status="blocked",
                summary="Preview generation is blocked until the draft bundle is ready.",
                operations=operations,
                validation=draft.validation,
                risks=draft.risks + ("preview generation skipped because the draft bundle is not ready",),
            )

        operations = tuple(self._preview_operation(operation) for operation in draft.operations)
        status = "ready" if all(operation.status == "ready" for operation in operations) else "blocked"
        return PreviewBundle(
            repository=draft.repository,
            number=draft.number,
            branch=draft.branch,
            status=status,
            summary=draft.summary,
            operations=operations,
            validation=draft.validation,
            risks=draft.risks,
        )

    def _preview_operation(self, operation: DraftOperation) -> PreviewOperation:
        target = Path(operation.absolute_path)
        current_exists = target.exists()
        current_sha256 = ""
        current_text = ""
        problems: list[str] = []

        if operation.status != "ready":
            problems.append(operation.validation_reason or "draft operation is not ready")

        if operation.action == "write_file":
            if operation.requested_operation == "create":
                if current_exists:
                    problems.append("target file already exists")
            else:
                if not current_exists:
                    problems.append("target file does not exist")
        elif operation.action == "delete_file":
            if not current_exists:
                problems.append("target file does not exist")
        else:
            problems.append(f"unsupported preview action: {operation.action!r}")

        if current_exists:
            if not target.is_file():
                problems.append("target path is not a regular file")
            else:
                data = target.read_bytes()
                current_sha256 = hashlib.sha256(data).hexdigest()
                try:
                    current_text = data.decode("utf-8")
                except UnicodeDecodeError:
                    problems.append("current file is not UTF-8 text")

        if operation.expected_sha256 and current_sha256 and current_sha256 != operation.expected_sha256:
            problems.append("current file hash no longer matches the expected precondition")

        diff = ""
        if not problems:
            diff = _render_diff(operation, current_text)
            if not diff:
                problems.append("generated operation does not produce a diff")

        status = "blocked" if problems else "ready"
        return PreviewOperation(
            path=operation.path,
            action=operation.action,
            absolute_path=operation.absolute_path,
            status=status,
            validation_reason="; ".join(problems) if problems else "ready",
            expected_sha256=operation.expected_sha256,
            current_sha256=current_sha256,
            current_exists=current_exists,
            diff=diff,
            diff_bytes=len(diff.encode("utf-8")) if diff else 0,
        )


def _render_diff(operation: DraftOperation, current_text: str) -> str:
    if operation.action == "write_file":
        before = current_text.splitlines(keepends=True)
        after = operation.content.splitlines(keepends=True)
        from_file = "/dev/null" if operation.requested_operation == "create" else f"a/{operation.path}"
        to_file = f"b/{operation.path}"
    else:
        before = current_text.splitlines(keepends=True)
        after = []
        from_file = f"a/{operation.path}"
        to_file = "/dev/null"

    diff_lines = difflib.unified_diff(
        before,
        after,
        fromfile=from_file,
        tofile=to_file,
        lineterm="",
    )
    return "\n".join(diff_lines)
