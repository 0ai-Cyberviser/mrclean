from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from mrclean.apply import DraftApplier
from mrclean.config import ModelConfig, MrCleanConfig, PolicyConfig, RepositoryConfig
from mrclean.policies import PolicyEngine
from mrclean.previews import PreviewBundle, PreviewOperation
from mrclean.workspace import WorkspaceSnapshot


def _write_preview(repo_path: Path, *, expected_sha256: str | None = None) -> PreviewBundle:
    current = "pytest\n"
    target = repo_path / "requirements-dev.txt"
    target.write_text(current, encoding="utf-8")
    digest = expected_sha256 or hashlib.sha256(current.encode("utf-8")).hexdigest()
    new_content = "pytest\npytest-cov\n"
    return PreviewBundle(
        repository="example/repo",
        number=32,
        branch="fix-ci",
        status="ready",
        summary="Update the dependency file narrowly.",
        operations=(
            PreviewOperation(
                path="requirements-dev.txt",
                requested_operation="modify",
                action="write_file",
                absolute_path=str(target),
                status="ready",
                validation_reason="ready",
                expected_sha256=digest,
                current_sha256=digest,
                current_exists=True,
                diff="--- a/requirements-dev.txt\n+++ b/requirements-dev.txt\n@@ -1 +1,2 @@\n pytest\n+pytest-cov\n",
                diff_bytes=88,
                content_sha256=hashlib.sha256(new_content.encode("utf-8")).hexdigest(),
                content=new_content,
            ),
        ),
        validation=("pytest -q",),
        risks=("Dependency updates can affect CI resolution.",),
    )


def _config(repo_path: Path) -> MrCleanConfig:
    return MrCleanConfig(
        name="mrclean",
        model=ModelConfig(provider="stub", name="fake-model"),
        policy=PolicyConfig(dry_run=False, allow_local_apply=True),
        repositories=(
            RepositoryConfig(
                name="example/repo",
                base_branch="main",
                local_path=str(repo_path),
            ),
        ),
    )


class FakeWorkspaceInspector:
    def __init__(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot

    def inspect(self, repository, pr_branch):
        return self.snapshot


class ApplyTests(unittest.TestCase):
    def test_applier_writes_file_when_policy_allows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            preview = _write_preview(Path(tmpdir))
            applier = DraftApplier(
                PolicyEngine(PolicyConfig(dry_run=False, allow_local_apply=True)),
                config=_config(Path(tmpdir)),
                workspace=FakeWorkspaceInspector(
                    WorkspaceSnapshot(path=tmpdir, current_branch="fix-ci", notes=())
                ),
            )

            result = applier.apply(preview)

            self.assertEqual(result.status, "applied")
            self.assertEqual(result.operations[0].status, "applied")
            self.assertTrue(result.operations[0].after_sha256)
            self.assertEqual((Path(tmpdir) / "requirements-dev.txt").read_text(encoding="utf-8"), "pytest\npytest-cov\n")

    def test_applier_blocks_when_hash_precondition_no_longer_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            preview = _write_preview(Path(tmpdir), expected_sha256="deadbeef")
            applier = DraftApplier(
                PolicyEngine(PolicyConfig(dry_run=False, allow_local_apply=True)),
                config=_config(Path(tmpdir)),
                workspace=FakeWorkspaceInspector(
                    WorkspaceSnapshot(path=tmpdir, current_branch="fix-ci", notes=())
                ),
            )

            result = applier.apply(preview)

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.operations[0].status, "blocked")
            self.assertIn("hash no longer matches", result.operations[0].validation_reason)
            self.assertEqual((Path(tmpdir) / "requirements-dev.txt").read_text(encoding="utf-8"), "pytest\n")

    def test_applier_reports_rolled_back_operations_truthfully(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.txt").write_text("one\n", encoding="utf-8")
            (root / "b.txt").write_text("two\n", encoding="utf-8")
            sha_a = hashlib.sha256(b"one\n").hexdigest()
            sha_b = hashlib.sha256(b"two\n").hexdigest()
            preview = PreviewBundle(
                repository="example/repo",
                number=32,
                branch="fix-ci",
                status="ready",
                summary="Update two files.",
                operations=(
                    PreviewOperation(
                        path="a.txt",
                        requested_operation="modify",
                        action="write_file",
                        absolute_path=str(root / "a.txt"),
                        status="ready",
                        validation_reason="ready",
                        expected_sha256=sha_a,
                        current_sha256=sha_a,
                        current_exists=True,
                        diff="diff",
                        diff_bytes=4,
                        content_sha256=hashlib.sha256(b"ONE\n").hexdigest(),
                        content="ONE\n",
                    ),
                    PreviewOperation(
                        path="b.txt",
                        requested_operation="modify",
                        action="write_file",
                        absolute_path=str(root / "b.txt"),
                        status="ready",
                        validation_reason="ready",
                        expected_sha256=sha_b,
                        current_sha256=sha_b,
                        current_exists=True,
                        diff="diff",
                        diff_bytes=4,
                        content_sha256=hashlib.sha256(b"TWO\n").hexdigest(),
                        content="TWO\n",
                    ),
                ),
                validation=(),
                risks=(),
            )
            class ExplodingApplier(DraftApplier):
                def _apply_operation(self, operation, target):
                    if operation.path == "b.txt":
                        raise RuntimeError("boom")
                    return super()._apply_operation(operation, target)

            applier = ExplodingApplier(
                PolicyEngine(PolicyConfig(dry_run=False, allow_local_apply=True)),
                config=_config(root),
                workspace=FakeWorkspaceInspector(
                    WorkspaceSnapshot(path=tmpdir, current_branch="fix-ci", notes=())
                ),
            )

            result = applier.apply(preview)

            self.assertEqual(result.status, "rolled_back")
            self.assertEqual(result.operations[0].status, "rolled_back")
            self.assertFalse(result.operations[0].changed)
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "one\n")
            self.assertEqual((root / "b.txt").read_text(encoding="utf-8"), "two\n")

    def test_applier_sets_executable_mode_for_new_shebang_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "script.sh"
            content = "#!/bin/sh\necho hi\n"
            preview = PreviewBundle(
                repository="example/repo",
                number=32,
                branch="fix-ci",
                status="ready",
                summary="Create a helper script.",
                operations=(
                    PreviewOperation(
                        path="script.sh",
                        requested_operation="create",
                        action="write_file",
                        absolute_path=str(target),
                        status="ready",
                        validation_reason="ready",
                        expected_sha256="",
                        current_sha256="",
                        current_exists=False,
                        diff="diff",
                        diff_bytes=4,
                        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        content=content,
                    ),
                ),
                validation=(),
                risks=(),
            )
            applier = DraftApplier(
                PolicyEngine(PolicyConfig(dry_run=False, allow_local_apply=True)),
                config=_config(root),
                workspace=FakeWorkspaceInspector(
                    WorkspaceSnapshot(path=tmpdir, current_branch="fix-ci", notes=())
                ),
            )

            result = applier.apply(preview)

            self.assertEqual(result.status, "applied")
            mode = os.stat(target).st_mode & 0o777
            self.assertEqual(mode, 0o755)

    def test_applier_blocks_when_workspace_branch_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            preview = _write_preview(Path(tmpdir))
            applier = DraftApplier(
                PolicyEngine(PolicyConfig(dry_run=False, allow_local_apply=True)),
                config=_config(Path(tmpdir)),
                workspace=FakeWorkspaceInspector(
                    WorkspaceSnapshot(path=tmpdir, current_branch="main", notes=())
                ),
            )

            result = applier.apply(preview)

            self.assertEqual(result.status, "blocked")
            self.assertIn("expected 'fix-ci'", result.operations[0].validation_reason)

    def test_applier_blocks_when_preview_target_escapes_repository_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            preview = _write_preview(Path(tmpdir))
            outside = Path(tmpdir).parent / "outside.txt"
            preview = PreviewBundle(
                repository=preview.repository,
                number=preview.number,
                branch=preview.branch,
                status=preview.status,
                summary=preview.summary,
                operations=(
                    PreviewOperation(
                        path="../outside.txt",
                        requested_operation="modify",
                        action="write_file",
                        absolute_path=str(outside),
                        status="ready",
                        validation_reason="ready",
                        expected_sha256=preview.operations[0].expected_sha256,
                        current_sha256=preview.operations[0].current_sha256,
                        current_exists=True,
                        diff=preview.operations[0].diff,
                        diff_bytes=preview.operations[0].diff_bytes,
                        content_sha256=preview.operations[0].content_sha256,
                        content=preview.operations[0].content,
                    ),
                ),
                validation=preview.validation,
                risks=preview.risks,
            )
            applier = DraftApplier(
                PolicyEngine(PolicyConfig(dry_run=False, allow_local_apply=True)),
                config=_config(Path(tmpdir)),
                workspace=FakeWorkspaceInspector(
                    WorkspaceSnapshot(path=tmpdir, current_branch="fix-ci", notes=())
                ),
            )

            result = applier.apply(preview)

            self.assertEqual(result.status, "blocked")
            self.assertIn("escapes the repository root", result.operations[0].validation_reason)


if __name__ == "__main__":
    unittest.main()
