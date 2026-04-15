from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from mrclean.apply import DraftApplier
from mrclean.config import PolicyConfig
from mrclean.policies import PolicyEngine
from mrclean.previews import PreviewBundle, PreviewOperation


def _preview(repo_path: Path, *, expected_sha256: str | None = None) -> PreviewBundle:
    current = "pytest\n"
    target = repo_path / "requirements-dev.txt"
    target.write_text(current, encoding="utf-8")
    digest = expected_sha256 or hashlib.sha256(current.encode("utf-8")).hexdigest()
    return PreviewBundle(
        repository="example/repo",
        number=32,
        branch="fix-ci",
        status="ready",
        summary="Update the dependency file narrowly.",
        operations=(
            PreviewOperation(
                path="requirements-dev.txt",
                action="write_file",
                absolute_path=str(target),
                status="ready",
                validation_reason="ready",
                expected_sha256=digest,
                current_sha256=digest,
                current_exists=True,
                diff="--- a/requirements-dev.txt\n+++ b/requirements-dev.txt\n@@ -1 +1,2 @@\n pytest\n+pytest-cov\n",
                diff_bytes=88,
            ),
        ),
        validation=("pytest -q",),
        risks=("Dependency updates can affect CI resolution.",),
    )


class ApplyTests(unittest.TestCase):
    def test_applier_writes_file_when_policy_allows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            preview = _preview(Path(tmpdir))
            applier = DraftApplier(PolicyEngine(PolicyConfig(dry_run=False, allow_local_apply=True)))

            result = applier.apply(
                preview,
                draft_contents={"requirements-dev.txt": "pytest\npytest-cov\n"},
            )

            self.assertEqual(result.status, "applied")
            self.assertEqual(result.operations[0].status, "applied")
            self.assertTrue(result.operations[0].after_sha256)
            self.assertEqual((Path(tmpdir) / "requirements-dev.txt").read_text(encoding="utf-8"), "pytest\npytest-cov\n")

    def test_applier_blocks_when_hash_precondition_no_longer_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            preview = _preview(Path(tmpdir), expected_sha256="deadbeef")
            applier = DraftApplier(PolicyEngine(PolicyConfig(dry_run=False, allow_local_apply=True)))

            result = applier.apply(
                preview,
                draft_contents={"requirements-dev.txt": "pytest\npytest-cov\n"},
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.operations[0].status, "blocked")
            self.assertIn("hash no longer matches", result.operations[0].validation_reason)
            self.assertEqual((Path(tmpdir) / "requirements-dev.txt").read_text(encoding="utf-8"), "pytest\n")


if __name__ == "__main__":
    unittest.main()
