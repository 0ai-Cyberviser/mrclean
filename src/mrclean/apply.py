from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile

from .policies import PlannedAction, PolicyEngine, PolicyViolation
from .previews import PreviewBundle, PreviewOperation


@dataclass(slots=True)
class AppliedOperation:
    path: str
    action: str
    absolute_path: str
    status: str
    validation_reason: str
    expected_sha256: str
    before_sha256: str
    after_sha256: str
    changed: bool


@dataclass(slots=True)
class ApplyTransaction:
    repository: str
    number: int
    branch: str
    status: str
    summary: str
    operations: tuple[AppliedOperation, ...]
    validation: tuple[str, ...]
    risks: tuple[str, ...]


@dataclass(slots=True)
class _BackupEntry:
    path: Path
    existed: bool
    data: bytes
    mode: int | None


class DraftApplier:
    def __init__(self, policy: PolicyEngine) -> None:
        self.policy = policy

    def apply(self, preview: PreviewBundle) -> ApplyTransaction:
        try:
            self.policy.require(
                PlannedAction(
                    kind="apply_patch",
                    repository=preview.repository,
                    branch=preview.branch,
                    summary=preview.summary,
                    file_count=len(preview.operations),
                    risky=True,
                )
            )
        except PolicyViolation as exc:
            return self._blocked_transaction(preview, str(exc))

        if preview.status != "ready":
            return self._blocked_transaction(preview, "preview bundle is not ready")

        preflight = self._preflight(preview.operations)
        if isinstance(preflight, str):
            return self._blocked_transaction(preview, preflight)

        backups, current_hashes = preflight
        applied: list[AppliedOperation] = []
        changed_backups: list[_BackupEntry] = []
        try:
            for operation in preview.operations:
                backup = backups[operation.path]
                self._apply_operation(operation, backup.path)
                changed_backups.append(backup)
                applied.append(self._applied_operation(operation, current_hashes[operation.path], changed=True))
        except Exception as exc:  # pragma: no cover - hard to force from public surface
            self._rollback(changed_backups)
            attempted = {operation.path for operation in preview.operations[: len(applied)]}
            partial: list[AppliedOperation] = []
            for operation in preview.operations:
                target = Path(operation.absolute_path)
                after_sha256 = ""
                if target.exists() and target.is_file():
                    after_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
                partial.append(
                    AppliedOperation(
                        path=operation.path,
                        action=operation.action,
                        absolute_path=operation.absolute_path,
                        status="rolled_back" if operation.path in attempted else "blocked",
                        validation_reason=f"apply failed and changes were rolled back: {exc}",
                        expected_sha256=operation.expected_sha256,
                        before_sha256=current_hashes.get(operation.path, ""),
                        after_sha256=after_sha256,
                        changed=False,
                    )
                )
            return ApplyTransaction(
                repository=preview.repository,
                number=preview.number,
                branch=preview.branch,
                status="rolled_back",
                summary="Apply failed and any partial local writes were rolled back.",
                operations=tuple(partial),
                validation=preview.validation,
                risks=preview.risks + ("apply failed and was rolled back",),
            )

        return ApplyTransaction(
            repository=preview.repository,
            number=preview.number,
            branch=preview.branch,
            status="applied",
            summary=preview.summary,
            operations=tuple(applied),
            validation=preview.validation,
            risks=preview.risks,
        )

    def _preflight(
        self,
        operations: tuple[PreviewOperation, ...],
    ) -> tuple[dict[str, _BackupEntry], dict[str, str]] | str:
        backups: dict[str, _BackupEntry] = {}
        current_hashes: dict[str, str] = {}
        for operation in operations:
            if operation.status != "ready":
                return operation.validation_reason or "preview operation is not ready"

            target = Path(operation.absolute_path)
            exists = target.exists()
            mode = None
            data = b""
            if exists:
                if not target.is_file():
                    return f"target path is not a regular file: {operation.path}"
                data = target.read_bytes()
                mode = target.stat().st_mode & 0o777
            digest = hashlib.sha256(data).hexdigest() if exists else ""
            if operation.expected_sha256 and digest != operation.expected_sha256:
                return f"current file hash no longer matches expected precondition for {operation.path}"

            if operation.action == "write_file":
                content_digest = hashlib.sha256(operation.content.encode("utf-8")).hexdigest()
                if operation.content_sha256 and content_digest != operation.content_sha256:
                    return f"preview content hash does not match declared content hash for {operation.path}"
                if not exists and target.parent and not target.parent.exists():
                    return f"target parent directory does not exist for {operation.path}"
            elif operation.action == "delete_file":
                if not exists:
                    return f"target file does not exist for {operation.path}"
            else:
                return f"unsupported apply action: {operation.action!r}"

            backups[operation.path] = _BackupEntry(path=target, existed=exists, data=data, mode=mode)
            current_hashes[operation.path] = digest
        return backups, current_hashes

    def _apply_operation(self, operation: PreviewOperation, target: Path) -> None:
        if operation.action == "delete_file":
            target.unlink()
            return
        if operation.content == "" and not operation.content_sha256:
            raise RuntimeError(f"missing preview content for {operation.path}")
        previous_mode = target.stat().st_mode & 0o777 if target.exists() else None
        mode = previous_mode if previous_mode is not None else _default_mode_for_content(operation.content)
        _write_atomic(target, operation.content.encode("utf-8"), mode=mode)

    def _applied_operation(self, operation: PreviewOperation, before_sha256: str, *, changed: bool) -> AppliedOperation:
        target = Path(operation.absolute_path)
        after_sha256 = ""
        if target.exists() and target.is_file():
            after_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
        return AppliedOperation(
            path=operation.path,
            action=operation.action,
            absolute_path=operation.absolute_path,
            status="applied" if changed else "blocked",
            validation_reason="applied" if changed else "not applied",
            expected_sha256=operation.expected_sha256,
            before_sha256=before_sha256,
            after_sha256=after_sha256,
            changed=changed,
        )

    def _rollback(self, backups: list[_BackupEntry]) -> None:
        for backup in reversed(backups):
            if backup.existed:
                _write_atomic(backup.path, backup.data, mode=backup.mode)
            elif backup.path.exists():
                backup.path.unlink()

    def _blocked_transaction(self, preview: PreviewBundle, reason: str) -> ApplyTransaction:
        operations = tuple(
            AppliedOperation(
                path=operation.path,
                action=operation.action,
                absolute_path=operation.absolute_path,
                status="blocked",
                validation_reason=reason,
                expected_sha256=operation.expected_sha256,
                before_sha256=operation.current_sha256,
                after_sha256=operation.current_sha256,
                changed=False,
            )
            for operation in preview.operations
        )
        return ApplyTransaction(
            repository=preview.repository,
            number=preview.number,
            branch=preview.branch,
            status="blocked",
            summary="Apply transaction is blocked.",
            operations=operations,
            validation=preview.validation,
            risks=preview.risks + (reason,),
        )


def _default_mode_for_content(content: str) -> int:
    return 0o755 if content.startswith("#!") else 0o644


def _write_atomic(path: Path, data: bytes, *, mode: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(data)
        temp_name = handle.name
    temp_path = Path(temp_name)
    if mode is not None:
        os.chmod(temp_path, mode)
    os.replace(temp_path, path)
