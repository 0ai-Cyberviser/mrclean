from __future__ import annotations

import unittest

from mrclean.dispatch import DispatchPlanner
from mrclean.monitor import ScanResult
from mrclean.policies import PolicyConfig, PolicyEngine
from mrclean.policies import PlannedAction


def _result(
    *,
    number: int = 32,
    category: str = "needs_attention",
    workspace_path: str = "/repo",
    workspace_notes: tuple[str, ...] = (),
    changed_files: tuple[str, ...] = ("a.py",),
    actions: tuple[PlannedAction, ...] = (),
) -> ScanResult:
    class _Plan:
        def __init__(self, actions):
            self.goal = "stabilize failing CI"
            self.actions = actions
            self.policy_notes = ()

    plan = None if category == "pending" else _Plan(actions)
    return ScanResult(
        repository="example/repo",
        number=number,
        title=f"Fix CI #{number}",
        url=f"https://github.com/example/repo/pull/{number}",
        branch=f"fix-ci-{number}",
        updated_at="2026-04-15T18:00:00Z",
        merge_state_status="UNSTABLE",
        category=category,
        failing_checks=("build-linux",) if category != "pending" else (),
        pending_checks=("build-linux",) if category == "pending" else (),
        changed_files=changed_files,
        workspace_path=workspace_path,
        workspace_branch=f"fix-ci-{number}" if not workspace_notes else "other-branch",
        workspace_notes=workspace_notes,
        plan=plan,
    )


class DispatchPlannerTests(unittest.TestCase):
    def test_dispatch_marks_matching_workspace_as_ready(self) -> None:
        actions = (
            PlannedAction(kind="inspect_signal", repository="example/repo", branch="fix-ci", summary="inspect"),
            PlannedAction(kind="edit_patch", repository="example/repo", branch="fix-ci", summary="edit", file_count=2),
            PlannedAction(kind="push_commit", repository="example/repo", branch="fix-ci", summary="push", file_count=2),
        )
        candidate = DispatchPlanner(PolicyEngine(PolicyConfig())).build((_result(actions=actions),))[0]

        self.assertEqual(candidate.status, "ready")
        self.assertTrue(candidate.workspace_ready)
        self.assertEqual(candidate.actions[0].allowed, True)
        self.assertEqual(candidate.actions[1].allowed, True)
        self.assertEqual(candidate.actions[2].allowed, False)
        self.assertEqual(candidate.actions[2].reason, "push is disabled by policy")

    def test_dispatch_marks_workspace_mismatch_as_inspect_only(self) -> None:
        actions = (
            PlannedAction(kind="inspect_signal", repository="example/repo", branch="fix-ci", summary="inspect"),
            PlannedAction(kind="edit_patch", repository="example/repo", branch="fix-ci", summary="edit", file_count=1),
        )
        candidate = DispatchPlanner(PolicyEngine(PolicyConfig())).build(
            (
                _result(
                    actions=actions,
                    workspace_notes=("local checkout is on 'other-branch', expected 'fix-ci'",),
                    changed_files=(),
                ),
            )
        )[0]

        self.assertEqual(candidate.status, "inspect_only")
        self.assertFalse(candidate.workspace_ready)
        self.assertEqual(candidate.actions[0].allowed, True)
        self.assertEqual(candidate.actions[1].allowed, False)
        self.assertIn("expected 'fix-ci'", candidate.actions[1].reason)

    def test_dispatch_defers_pending_items(self) -> None:
        candidate = DispatchPlanner(PolicyEngine(PolicyConfig())).build((_result(category="pending"),))[0]
        self.assertEqual(candidate.status, "deferred")
        self.assertEqual(candidate.actions, ())

    def test_dispatch_sorts_ready_items_ahead_of_inspect_only(self) -> None:
        ready = _result(
            number=32,
            actions=(
                PlannedAction(kind="inspect_signal", repository="example/repo", branch="fix-ci", summary="inspect"),
                PlannedAction(kind="edit_patch", repository="example/repo", branch="fix-ci", summary="edit", file_count=1),
            ),
        )
        inspect_only = _result(
            number=15,
            actions=(
                PlannedAction(kind="inspect_signal", repository="example/repo", branch="fix-ci", summary="inspect"),
                PlannedAction(kind="edit_patch", repository="example/repo", branch="fix-ci", summary="edit", file_count=1),
            ),
            workspace_notes=("local checkout is on 'other-branch', expected 'fix-ci'",),
            changed_files=(),
        )

        candidates = DispatchPlanner(PolicyEngine(PolicyConfig())).build((inspect_only, ready))
        self.assertEqual((candidates[0].number, candidates[0].status), (32, "ready"))
        self.assertEqual((candidates[1].number, candidates[1].status), (15, "inspect_only"))


if __name__ == "__main__":
    unittest.main()
