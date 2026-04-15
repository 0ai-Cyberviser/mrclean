from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from mrclean.config import MrCleanConfig, sample_config
from mrclean.github import CheckStatus, PullRequestSnapshot
from mrclean.monitor import RepositoryScanner
from mrclean.workspace import WorkspaceSnapshot


class FakeGitHub:
    def __init__(self, snapshots: dict[str, tuple[PullRequestSnapshot, ...]]) -> None:
        self.snapshots = snapshots

    def list_open_pull_requests(self, repository: str) -> tuple[PullRequestSnapshot, ...]:
        return self.snapshots.get(repository, ())


class FakeWorkspace:
    def __init__(self, snapshots: dict[tuple[str, str], WorkspaceSnapshot | None]) -> None:
        self.snapshots = snapshots

    def inspect(self, repository, pr_branch: str) -> WorkspaceSnapshot | None:
        return self.snapshots.get((repository.name, pr_branch))


class MonitorTests(unittest.TestCase):
    def test_scan_only_builds_plans_for_failing_prs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mrclean.toml"
            path.write_text(sample_config(), encoding="utf-8")
            config = MrCleanConfig.from_toml(path)

        github = FakeGitHub(
            {
                "0ai-Cyberviser/Hancock": (
                    PullRequestSnapshot(
                        repository="0ai-Cyberviser/Hancock",
                        number=60,
                        title="Fix diagnostics",
                        url="https://github.com/0ai-Cyberviser/Hancock/pull/60",
                        updated_at="2026-04-15T18:00:00Z",
                        head_ref_name="codex/diag",
                        merge_state_status="UNSTABLE",
                        checks=(
                            CheckStatus(name="build-linux", status="COMPLETED", conclusion="FAILURE"),
                        ),
                    ),
                ),
                "0ai-Cyberviser/CyberViser-ViserHub": (
                    PullRequestSnapshot(
                        repository="0ai-Cyberviser/CyberViser-ViserHub",
                        number=32,
                        title="Fix fuzzing CI",
                        url="https://github.com/0ai-Cyberviser/CyberViser-ViserHub/pull/32",
                        updated_at="2026-04-15T18:00:00Z",
                        head_ref_name="copilot/fix-fuzzing",
                        merge_state_status="UNSTABLE",
                        checks=(
                            CheckStatus(name="fuzz-pr", status="IN_PROGRESS", conclusion=""),
                        ),
                    ),
                ),
            }
        )

        workspace = FakeWorkspace(
            {
                (
                    "0ai-Cyberviser/Hancock",
                    "codex/diag",
                ): WorkspaceSnapshot(
                    path="/home/oai/Hancock",
                    current_branch="codex/diag",
                    base_ref="origin/main",
                    changed_files=("hancock_agent.py", "tests/test_hancock_api.py"),
                ),
                (
                    "0ai-Cyberviser/CyberViser-ViserHub",
                    "copilot/fix-fuzzing",
                ): WorkspaceSnapshot(
                    path="/home/oai/pr-audits/CyberViser-ViserHub",
                    current_branch="copilot/15315-awaiting-approval",
                    notes=("local checkout is on 'copilot/15315-awaiting-approval', expected 'copilot/fix-fuzzing'",),
                ),
            }
        )

        results = RepositoryScanner(config, github=github, workspace=workspace).scan()
        self.assertEqual(len(results), 2)

        failing = next(item for item in results if item.category == "needs_attention")
        pending = next(item for item in results if item.category == "pending")

        self.assertEqual(failing.number, 60)
        self.assertIsNotNone(failing.plan)
        self.assertEqual(failing.changed_files, ("hancock_agent.py", "tests/test_hancock_api.py"))
        self.assertEqual(failing.workspace_branch, "codex/diag")
        self.assertEqual(pending.number, 32)
        self.assertIsNone(pending.plan)
        self.assertEqual(
            pending.workspace_notes,
            ("local checkout is on 'copilot/15315-awaiting-approval', expected 'copilot/fix-fuzzing'",),
        )

    def test_scan_marks_older_duplicate_failures_as_superseded_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mrclean.toml"
            path.write_text(sample_config(), encoding="utf-8")
            config = MrCleanConfig.from_toml(path)

        github = FakeGitHub(
            {
                "0ai-Cyberviser/CyberViser-ViserHub": (
                    PullRequestSnapshot(
                        repository="0ai-Cyberviser/CyberViser-ViserHub",
                        number=29,
                        title="Older fuzzing fix",
                        url="https://github.com/0ai-Cyberviser/CyberViser-ViserHub/pull/29",
                        updated_at="2026-04-14T18:00:00Z",
                        head_ref_name="copilot/older-fuzz-fix",
                        merge_state_status="UNSTABLE",
                        checks=(
                            CheckStatus(name="fuzz-pr", status="COMPLETED", conclusion="FAILURE"),
                        ),
                    ),
                    PullRequestSnapshot(
                        repository="0ai-Cyberviser/CyberViser-ViserHub",
                        number=32,
                        title="Newer fuzzing fix",
                        url="https://github.com/0ai-Cyberviser/CyberViser-ViserHub/pull/32",
                        updated_at="2026-04-15T18:00:00Z",
                        head_ref_name="copilot/newer-fuzz-fix",
                        merge_state_status="UNSTABLE",
                        checks=(
                            CheckStatus(name="fuzz-pr", status="COMPLETED", conclusion="FAILURE"),
                        ),
                    ),
                ),
            }
        )

        results = RepositoryScanner(config, github=github, workspace=FakeWorkspace({})).scan(
            repositories=("0ai-Cyberviser/CyberViser-ViserHub",)
        )
        self.assertEqual(len(results), 2)

        current = next(item for item in results if item.number == 32)
        stale = next(item for item in results if item.number == 29)

        self.assertEqual(current.category, "needs_attention")
        self.assertEqual(current.superseded_by, None)
        self.assertIn("push_commit", tuple(action.kind for action in current.plan.actions))

        self.assertEqual(stale.category, "superseded_candidate")
        self.assertEqual(stale.superseded_by, 32)
        self.assertIsNotNone(stale.plan)
        self.assertIn("review_pr_scope", tuple(action.kind for action in stale.plan.actions))
        self.assertIn("close_pr", tuple(action.kind for action in stale.plan.actions))


if __name__ == "__main__":
    unittest.main()
