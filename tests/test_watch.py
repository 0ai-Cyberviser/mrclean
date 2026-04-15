from __future__ import annotations

import unittest

from mrclean.assess import AssessmentReport
from mrclean.dispatch import DispatchCandidate
from mrclean.monitor import ScanResult
from mrclean.watch import RepositoryWatcher


class FakeScanner:
    def __init__(self, sequences: list[tuple[ScanResult, ...]]) -> None:
        self.sequences = sequences
        self.calls = 0

    def scan(self, repositories=None, include_healthy=False) -> tuple[ScanResult, ...]:
        index = min(self.calls, len(self.sequences) - 1)
        self.calls += 1
        return self.sequences[index]


class FakePlanner:
    def build(self, results):
        return (
            DispatchCandidate(
                repository="example/repo",
                number=32,
                title="PR 32",
                url="https://github.com/example/repo/pull/32",
                branch="branch-32",
                category="needs_attention",
                status="ready",
                priority=0,
                workspace_ready=True,
                workspace_reason="workspace matches PR branch",
                changed_files=("a.py",),
                actions=(),
                assessment_outcome="unknown",
            ),
        )


class FakeAssessor:
    def __init__(self) -> None:
        self.calls = 0

    def assess(self, results, candidates):
        outcomes = ("verify", "hold")
        outcome = outcomes[min(self.calls, len(outcomes) - 1)]
        self.calls += 1
        return (
            AssessmentReport(
                repository="example/repo",
                number=32,
                title="PR 32",
                url="https://github.com/example/repo/pull/32",
                branch="branch-32",
                category="needs_attention",
                dispatch_status="ready",
                outcome=outcome,
                false_positive_risk="medium" if outcome == "verify" else "high",
                runtime_risk="medium",
                confidence=80 if outcome == "verify" else 60,
                recommended_action="verify first" if outcome == "verify" else "hold and review",
                findings=(),
            ),
        )


def _result(
    number: int,
    *,
    category: str = "needs_attention",
    failing_checks: tuple[str, ...] = ("fuzz-pr",),
    changed_files: tuple[str, ...] = (),
) -> ScanResult:
    return ScanResult(
        repository="example/repo",
        number=number,
        title=f"PR {number}",
        url=f"https://github.com/example/repo/pull/{number}",
        branch=f"branch-{number}",
        updated_at="2026-04-15T18:00:00Z",
        merge_state_status="UNSTABLE",
        category=category,
        failing_checks=failing_checks,
        pending_checks=(),
        changed_files=changed_files,
        workspace_path="/repo",
        workspace_branch=f"branch-{number}",
        workspace_notes=(),
    )


class WatcherTests(unittest.TestCase):
    def test_watcher_emits_appeared_updated_and_resolved_events(self) -> None:
        watcher = RepositoryWatcher(
            FakeScanner(
                [
                    (_result(32, changed_files=("a.py",)),),
                    (_result(32, changed_files=("a.py", "b.py")),),
                    (),
                ]
            )
        )

        first = watcher.poll()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].kind, "appeared")
        self.assertEqual(first[0].current.number, 32)

        second = watcher.poll()
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].kind, "updated")
        self.assertEqual(second[0].previous.changed_files, ("a.py",))
        self.assertEqual(second[0].current.changed_files, ("a.py", "b.py"))

        third = watcher.poll()
        self.assertEqual(len(third), 1)
        self.assertEqual(third[0].kind, "resolved")
        self.assertEqual(third[0].previous.number, 32)

    def test_watcher_suppresses_unchanged_results(self) -> None:
        watcher = RepositoryWatcher(
            FakeScanner(
                [
                    (_result(32),),
                    (_result(32),),
                ]
            )
        )

        self.assertEqual(len(watcher.poll()), 1)
        self.assertEqual(watcher.poll(), ())

    def test_watcher_emits_updated_event_when_assessment_changes(self) -> None:
        watcher = RepositoryWatcher(
            FakeScanner(
                [
                    (_result(32),),
                    (_result(32),),
                ]
            ),
            planner=FakePlanner(),
            assessor=FakeAssessor(),
        )

        first = watcher.poll()
        self.assertEqual(first[0].current_assessment.outcome, "verify")

        second = watcher.poll()
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].kind, "updated")
        self.assertEqual(second[0].previous_assessment.outcome, "verify")
        self.assertEqual(second[0].current_assessment.outcome, "hold")


if __name__ == "__main__":
    unittest.main()
