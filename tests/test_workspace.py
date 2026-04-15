from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from mrclean.config import RepositoryConfig
from mrclean.workspace import GitWorkspaceInspector


class WorkspaceInspectorTests(unittest.TestCase):
    def test_inspect_collects_changed_files_when_branch_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            responses = {
                (str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"): "feature/ci-fix\n",
                (str(repo_path), "status", "--short"): "",
                (str(repo_path), "rev-parse", "--verify", "origin/main"): "abc123\n",
                (str(repo_path), "diff", "--name-only", "origin/main...HEAD"): "a.py\nb.py\n",
            }

            def runner(path, args):
                return responses[(str(path), *args)]

            snapshot = GitWorkspaceInspector(runner=runner).inspect(
                RepositoryConfig(name="example/repo", base_branch="main", local_path=str(repo_path)),
                "feature/ci-fix",
            )

            self.assertEqual(snapshot.current_branch, "feature/ci-fix")
            self.assertEqual(snapshot.base_ref, "origin/main")
            self.assertEqual(snapshot.changed_files, ("a.py", "b.py"))
            self.assertEqual(snapshot.notes, ())

    def test_inspect_reports_branch_mismatch_without_faking_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            responses = {
                (str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"): "feature/current\n",
                (str(repo_path), "status", "--short"): " M README.md\n",
            }

            def runner(path, args):
                key = (str(path), *args)
                if key not in responses:
                    raise subprocess.CalledProcessError(returncode=1, cmd=["git", *args])
                return responses[key]

            snapshot = GitWorkspaceInspector(runner=runner).inspect(
                RepositoryConfig(name="example/repo", base_branch="main", local_path=str(repo_path)),
                "feature/pr-branch",
            )

            self.assertEqual(snapshot.current_branch, "feature/current")
            self.assertEqual(snapshot.changed_files, ())
            self.assertEqual(
                snapshot.notes,
                (
                    "local checkout has uncommitted changes",
                    "local checkout is on 'feature/current', expected 'feature/pr-branch'",
                ),
            )


if __name__ == "__main__":
    unittest.main()
