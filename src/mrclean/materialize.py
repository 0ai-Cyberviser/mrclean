from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .config import MrCleanConfig, RepositoryConfig
from .dispatch import DispatchCandidate
from .intents import EditIntent, IntentEdit
from .workspace import GitWorkspaceInspector, WorkspaceSnapshot


@dataclass(slots=True)
class MaterializedEdit:
    path: str
    operation: str
    summary: str
    reason: str
    absolute_path: str
    status: str
    validation_reason: str
    exists: bool
    in_branch_scope: bool
    size_bytes: int | None = None
    sha256: str = ""
    preview: str = ""


@dataclass(slots=True)
class MaterializedIntent:
    repository: str
    number: int
    branch: str
    workspace_path: str
    workspace_branch: str
    workspace_ready: bool
    workspace_reason: str
    status: str
    summary: str
    edits: tuple[MaterializedEdit, ...]
    validation: tuple[str, ...]
    risks: tuple[str, ...]


class IntentMaterializer:
    def __init__(self, config: MrCleanConfig, workspace: GitWorkspaceInspector | None = None, preview_chars: int = 500) -> None:
        self.config = config
        self.workspace = workspace or GitWorkspaceInspector()
        self.preview_chars = preview_chars

    def materialize(self, candidate: DispatchCandidate, intent: EditIntent) -> MaterializedIntent:
        repository = self.config.get_repository(intent.repository)
        workspace_path = repository.local_path or ""
        workspace_snapshot = self.workspace.inspect(repository, intent.branch)
        workspace_branch, workspace_ready, workspace_reason = _workspace_state(repository, intent.branch, workspace_snapshot)

        edits = tuple(
            self._materialize_edit(repository, candidate, edit, workspace_ready)
            for edit in intent.edits
        )
        status = "ready" if workspace_ready and all(edit.status == "ready" for edit in edits) else "blocked"
        return MaterializedIntent(
            repository=intent.repository,
            number=intent.number,
            branch=intent.branch,
            workspace_path=workspace_path,
            workspace_branch=workspace_branch,
            workspace_ready=workspace_ready,
            workspace_reason=workspace_reason,
            status=status,
            summary=intent.summary,
            edits=edits,
            validation=intent.validation,
            risks=intent.risks,
        )

    def _materialize_edit(
        self,
        repository: RepositoryConfig,
        candidate: DispatchCandidate,
        edit: IntentEdit,
        workspace_ready: bool,
    ) -> MaterializedEdit:
        workspace_root = Path(repository.local_path or "")
        absolute_path = workspace_root / edit.path if repository.local_path else Path(edit.path)
        exists = absolute_path.exists()
        in_branch_scope = not candidate.changed_files or edit.path in candidate.changed_files or edit.operation == "create"

        status = "ready"
        reasons: list[str] = []

        if not repository.local_path:
            status = "blocked"
            reasons.append("repository.local_path is not configured")
        if not workspace_ready:
            status = "blocked"
            reasons.append("workspace is not ready for this branch")
        if edit.operation in {"modify", "delete"} and not exists:
            status = "blocked"
            reasons.append("target file does not exist")
        if edit.operation == "create" and exists:
            status = "blocked"
            reasons.append("target file already exists")
        if edit.operation == "create" and repository.local_path and not absolute_path.parent.exists():
            status = "blocked"
            reasons.append("target parent directory does not exist")
        if exists and not absolute_path.is_file():
            status = "blocked"
            reasons.append("target path is not a regular file")
        if not in_branch_scope:
            status = "blocked"
            reasons.append("target path is outside the current branch diff")

        size_bytes, sha256, preview = _file_metadata(absolute_path, self.preview_chars) if exists else (None, "", "")
        return MaterializedEdit(
            path=edit.path,
            operation=edit.operation,
            summary=edit.summary,
            reason=edit.reason,
            absolute_path=str(absolute_path),
            status=status,
            validation_reason="; ".join(reasons) if reasons else "ready",
            exists=exists,
            in_branch_scope=in_branch_scope,
            size_bytes=size_bytes,
            sha256=sha256,
            preview=preview,
        )


def _workspace_state(
    repository: RepositoryConfig,
    branch: str,
    snapshot: WorkspaceSnapshot | None,
) -> tuple[str, bool, str]:
    if not repository.local_path:
        return "", False, "repository.local_path is not configured"
    if snapshot is None:
        return "", False, "workspace inspection returned no data"
    branch_name = snapshot.current_branch
    if snapshot.notes:
        return branch_name, False, "; ".join(snapshot.notes)
    if branch and branch_name and branch_name != branch:
        return branch_name, False, f"local checkout is on {branch_name!r}, expected {branch!r}"
    return branch_name, True, "workspace matches intent branch"


def _file_metadata(path: Path, preview_chars: int) -> tuple[int | None, str, str]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode("utf-8")
        preview = text[:preview_chars]
    except UnicodeDecodeError:
        preview = "<binary file>"
    return len(data), digest, preview
