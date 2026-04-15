from __future__ import annotations

import unittest

from mrclean.config import PolicyConfig
from mrclean.policies import PlannedAction, PolicyEngine


class PolicyEngineTests(unittest.TestCase):
    def test_push_to_protected_branch_is_blocked(self) -> None:
        engine = PolicyEngine(PolicyConfig(dry_run=False, allow_push=True))
        result = engine.review(
            PlannedAction(
                kind="push_commit",
                repository="example/repo",
                branch="main",
                summary="push a cleanup fix",
                file_count=1,
            )
        )
        self.assertFalse(result.allowed)
        self.assertIn("protected", result.reason)

    def test_large_patch_is_blocked(self) -> None:
        engine = PolicyEngine(PolicyConfig(max_patch_files=2))
        result = engine.review(
            PlannedAction(
                kind="edit_patch",
                repository="example/repo",
                branch="feature",
                summary="wide patch",
                file_count=4,
            )
        )
        self.assertFalse(result.allowed)
        self.assertIn("limit is 2", result.reason)


if __name__ == "__main__":
    unittest.main()

