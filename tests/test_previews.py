from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from mrclean.drafts import DraftBundle, DraftOperation
from mrclean.previews import DraftPreviewer


def _draft(repo_path: Path, *, expected_sha256: str | None = None) -> DraftBundle:
    current = "pytest\n"
    target = repo_path / "requirements-dev.txt"
    target.write_text(current, encoding="utf-8")
    digest = expected_sha256 or hashlib.sha256(current.encode("utf-8")).hexdigest()
    return DraftBundle(
        repository="example/repo",
        number=32,
        branch="fix-ci",
        status="ready",
        summary="Update the dependency file narrowly.",
        operations=(
            DraftOperation(
                path="requirements-dev.txt",
                requested_operation="modify",
                action="write_file",
                summary="Add pytest-cov.",
                reason="Coverage workflow requires it.",
                absolute_path=str(target),
                status="ready",
                validation_reason="ready",
                expected_sha256=digest,
                content_sha256=hashlib.sha256("pytest\npytest-cov\n".encode("utf-8")).hexdigest(),
                content_bytes=len("pytest\npytest-cov\n".encode("utf-8")),
                content_preview="pytest\npytest-cov\n",
                content="pytest\npytest-cov\n",
            ),
        ),
        validation=("pytest -q",),
        risks=("Dependency updates can affect CI resolution.",),
        model_provider="fake",
        model_name="fake-model",
        raw={"provider": "fake"},
    )


class PreviewTests(unittest.TestCase):
    def test_previewer_renders_unified_diff_for_ready_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = _draft(Path(tmpdir))
            preview = DraftPreviewer().preview(bundle)

            self.assertEqual(preview.status, "ready")
            self.assertEqual(preview.operations[0].status, "ready")
            self.assertIn("--- a/requirements-dev.txt", preview.operations[0].diff)
            self.assertIn("+++ b/requirements-dev.txt", preview.operations[0].diff)
            self.assertIn("+pytest-cov", preview.operations[0].diff)

    def test_previewer_blocks_when_current_hash_no_longer_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = _draft(Path(tmpdir), expected_sha256="deadbeef")
            preview = DraftPreviewer().preview(bundle)

            self.assertEqual(preview.status, "blocked")
            self.assertEqual(preview.operations[0].status, "blocked")
            self.assertIn("hash no longer matches", preview.operations[0].validation_reason)


if __name__ == "__main__":
    unittest.main()
