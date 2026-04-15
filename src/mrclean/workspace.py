from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .config import RepositoryConfig


@dataclass(slots=True)
class WorkspaceSnapshot:
    path: str
    current_branch: str = ""
    base_ref: str = ""
    changed_files: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class GitWorkspaceInspector:
    def __init__(self, runner: callable | None = None) -> None:
        self._runner = runner or _run_git

    def inspect(self, repository: RepositoryConfig, pr_branch: str) -> WorkspaceSnapshot | None:
        if not repository.local_path:
            return None

        workspace_path = Path(repository.local_path)
        if not workspace_path.exists():
            return WorkspaceSnapshot(
                path=str(workspace_path),
                notes=("configured local_path does not exist",),
            )

        notes: list[str] = []
        current_branch = self._safe_git(workspace_path, "rev-parse", "--abbrev-ref", "HEAD").strip()
        status_output = self._safe_git(workspace_path, "status", "--short").strip()
        if status_output:
            notes.append("local checkout has uncommitted changes")

        if pr_branch and current_branch and current_branch != pr_branch:
            notes.append(f"local checkout is on {current_branch!r}, expected {pr_branch!r}")
            return WorkspaceSnapshot(
                path=str(workspace_path),
                current_branch=current_branch,
                notes=tuple(notes),
            )

        base_ref = self._resolve_base_ref(workspace_path, repository.base_branch)
        if not base_ref:
            notes.append(f"could not resolve base branch {repository.base_branch!r} locally")
            return WorkspaceSnapshot(
                path=str(workspace_path),
                current_branch=current_branch,
                notes=tuple(notes),
            )

        changed_output = self._safe_git(workspace_path, "diff", "--name-only", f"{base_ref}...HEAD")
        changed_files = tuple(line for line in changed_output.splitlines() if line.strip())
        return WorkspaceSnapshot(
            path=str(workspace_path),
            current_branch=current_branch,
            base_ref=base_ref,
            changed_files=changed_files,
            notes=tuple(notes),
        )

    def _resolve_base_ref(self, workspace_path: Path, base_branch: str) -> str:
        candidates = (f"origin/{base_branch}", base_branch)
        for candidate in candidates:
            if self._git_exists(workspace_path, "rev-parse", "--verify", candidate):
                return candidate
        return ""

    def _git_exists(self, workspace_path: Path, *args: str) -> bool:
        try:
            self._runner(workspace_path, list(args))
        except subprocess.CalledProcessError:
            return False
        return True

    def _safe_git(self, workspace_path: Path, *args: str) -> str:
        try:
            return self._runner(workspace_path, list(args))
        except subprocess.CalledProcessError:
            return ""


def _run_git(workspace_path: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(workspace_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout
