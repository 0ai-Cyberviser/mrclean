from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from mrclean.config import MrCleanConfig
from mrclean.dispatch import DispatchAction, DispatchCandidate
from mrclean.intents import EditIntent, IntentEdit
from mrclean.materialize import IntentMaterializer
from mrclean.workspace import WorkspaceSnapshot


class FakeWorkspace:
    def __init__(self, snapshot: WorkspaceSnapshot | None) -> None:
        self.snapshot = snapshot

    def inspect(self, repository, pr_branch: str):
        return self.snapshot


def _config_text(local_path: str) -> str:
    return f"""name = "mrclean"

[model]
provider = "stub"
name = "gpt-5.4-mini"

[policy]
dry_run = true
allow_push = false
allow_close_stale_prs = false
allow_force_push = false
max_patch_files = 5
protected_branches = ["main", "master"]

[[repositories]]
name = "example/repo"
base_branch = "main"
local_path = "{local_path}"
monitored_checks = ["build-linux"]
"""


def _candidate(changed_files: tuple[str, ...]) -> DispatchCandidate:
    return DispatchCandidate(
        repository="example/repo",
        number=32,
        title="Fix CI",
        url="https://github.com/example/repo/pull/32",
        branch="fix-ci",
        category="needs_attention",
        status="ready",
        priority=0,
        workspace_ready=True,
        workspace_reason="workspace matches PR branch",
        changed_files=changed_files,
        actions=(DispatchAction("edit_patch", "edit", True, "allowed", "git diff --stat"),),
    )


def _intent(path: str, operation: str = "modify") -> EditIntent:
    return EditIntent(
        repository="example/repo",
        number=32,
        branch="fix-ci",
        candidate_status="ready",
        run_status="prepared",
        summary="Fix the active CI issue narrowly.",
        edits=(IntentEdit(path=path, operation=operation, summary="edit file", reason="needed"),),
        validation=("pytest -q",),
        risks=("low",),
        model_provider="stub",
        model_name="gpt-5.4-mini",
        raw={},
    )


class MaterializeTests(unittest.TestCase):
    def test_materializer_resolves_existing_file_in_branch_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            target = repo_path / "requirements-dev.txt"
            target.write_text("pytest\n", encoding="utf-8")

            config = MrCleanConfig.from_toml_text(_config_text(str(repo_path)))
            materializer = IntentMaterializer(
                config,
                workspace=FakeWorkspace(
                    WorkspaceSnapshot(
                        path=str(repo_path),
                        current_branch="fix-ci",
                        base_ref="origin/main",
                        changed_files=("requirements-dev.txt",),
                    )
                ),
            )
            result = materializer.materialize(_candidate(("requirements-dev.txt",)), _intent("requirements-dev.txt"))

            self.assertEqual(result.status, "ready")
            self.assertTrue(result.workspace_ready)
            self.assertEqual(result.edits[0].status, "ready")
            self.assertTrue(result.edits[0].exists)
            self.assertTrue(result.edits[0].sha256)

    def test_materializer_blocks_out_of_scope_or_mismatched_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            target = repo_path / "requirements-dev.txt"
            target.write_text("pytest\n", encoding="utf-8")

            config = MrCleanConfig.from_toml_text(_config_text(str(repo_path)))
            materializer = IntentMaterializer(
                config,
                workspace=FakeWorkspace(
                    WorkspaceSnapshot(
                        path=str(repo_path),
                        current_branch="other-branch",
                        notes=("local checkout is on 'other-branch', expected 'fix-ci'",),
                    )
                ),
            )
            result = materializer.materialize(_candidate(("another-file.txt",)), _intent("requirements-dev.txt"))

            self.assertEqual(result.status, "blocked")
            self.assertFalse(result.workspace_ready)
            self.assertEqual(result.edits[0].status, "blocked")
            self.assertIn("outside the current branch diff", result.edits[0].validation_reason)


if __name__ == "__main__":
    unittest.main()
