from __future__ import annotations

import subprocess
import unittest

from mrclean.dispatch import DispatchAction, DispatchCandidate
from mrclean.runner import LocalRunner


class LocalRunnerTests(unittest.TestCase):
    def test_runner_executes_safe_allowed_actions(self) -> None:
        commands: list[str] = []

        def runner(command: str) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="ok\n",
                stderr="",
            )

        candidate = DispatchCandidate(
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
            changed_files=("a.py",),
            actions=(
                DispatchAction("inspect_signal", "inspect", True, "allowed", "gh pr view 32"),
                DispatchAction("edit_patch", "edit", True, "allowed", "git -C /repo diff --stat"),
                DispatchAction("push_commit", "push", False, "push is disabled by policy", "git push"),
            ),
            assessment_outcome="actionable",
        )

        session = LocalRunner(command_runner=runner).run((candidate,), limit=1)[0]
        self.assertEqual(session.run_status, "prepared")
        self.assertEqual(commands, ["gh pr view 32", "git -C /repo diff --stat"])
        self.assertEqual(session.executions[0].status, "executed")
        self.assertEqual(session.executions[2].status, "skipped")

    def test_runner_marks_inspect_only_candidates_as_inspected(self) -> None:
        def runner(command: str) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="inspect\n", stderr="")

        candidate = DispatchCandidate(
            repository="example/repo",
            number=15,
            title="Inspect only",
            url="https://github.com/example/repo/pull/15",
            branch="other-branch",
            category="needs_attention",
            status="inspect_only",
            priority=0,
            workspace_ready=False,
            workspace_reason="branch mismatch",
            changed_files=(),
            actions=(
                DispatchAction("inspect_signal", "inspect", True, "allowed", "gh pr view 15"),
                DispatchAction("edit_patch", "edit", False, "branch mismatch", "git diff"),
            ),
            assessment_outcome="verify",
        )

        session = LocalRunner(command_runner=runner).run((candidate,), limit=1, allow_verify=True)[0]
        self.assertEqual(session.run_status, "inspected")
        self.assertEqual(session.executions[0].status, "executed")
        self.assertEqual(session.executions[1].status, "skipped")

    def test_runner_skips_verify_candidates_without_override(self) -> None:
        candidate = DispatchCandidate(
            repository="example/repo",
            number=15,
            title="Inspect only",
            url="https://github.com/example/repo/pull/15",
            branch="other-branch",
            category="needs_attention",
            status="inspect_only",
            priority=0,
            workspace_ready=False,
            workspace_reason="branch mismatch",
            changed_files=(),
            actions=(DispatchAction("inspect_signal", "inspect", True, "allowed", "gh pr view 15"),),
            assessment_outcome="verify",
        )

        sessions = LocalRunner().run((candidate,), limit=1)
        self.assertEqual(sessions, ())

    def test_runner_returns_empty_for_missing_target_pr(self) -> None:
        candidate = DispatchCandidate(
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
            changed_files=("a.py",),
            actions=(),
            assessment_outcome="actionable",
        )

        sessions = LocalRunner().run((candidate,), pr_number=99)
        self.assertEqual(sessions, ())


if __name__ == "__main__":
    unittest.main()
