from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
