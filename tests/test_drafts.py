from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from mrclean.config import MrCleanConfig
from mrclean.drafts import DraftGenerator
from mrclean.materialize import MaterializedEdit, MaterializedIntent
from mrclean.models import CompletionResponse


class FakeModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return CompletionResponse(
            content=self.content,
            raw={"provider": "fake", "model": "fake-model"},
        )


def _config_text(local_path: str) -> str:
    return f"""name = "mrclean"

[model]
provider = "stub"
name = "gpt-5.4-mini"

[policy]
dry_run = true
allow_push = false
allow_close_stale_prs = false
allow_force_push = false
max_patch_files = 5
protected_branches = ["main", "master"]

[[repositories]]
name = "example/repo"
base_branch = "main"
local_path = "{local_path}"
monitored_checks = ["build-linux"]
"""


def _materialized(repo_path: Path, *, status: str = "ready", edit_status: str = "ready") -> MaterializedIntent:
    content = "pytest\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    target = repo_path / "requirements-dev.txt"
    target.write_text(content, encoding="utf-8")
    return MaterializedIntent(
        repository="example/repo",
        number=32,
        branch="fix-ci",
        workspace_path=str(repo_path),
        workspace_branch="fix-ci",
        workspace_ready=status == "ready",
        workspace_reason="workspace matches intent branch" if status == "ready" else "workspace is dirty",
        status=status,
        summary="Fix the active CI issue narrowly.",
        edits=(
            MaterializedEdit(
                path="requirements-dev.txt",
                operation="modify",
                summary="Add pytest-cov.",
                reason="Coverage workflow requires it.",
                absolute_path=str(target),
                status=edit_status,
                validation_reason="ready" if edit_status == "ready" else "workspace is not ready for this branch",
                exists=True,
                in_branch_scope=True,
                size_bytes=len(content.encode("utf-8")),
                sha256=digest,
                preview=content,
            ),
        ),
        validation=("pytest -q",),
        risks=("Dependency updates can affect CI resolution.",),
    )


class DraftTests(unittest.TestCase):
    def test_draft_generator_returns_ready_bundle_for_text_modify(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            config = MrCleanConfig.from_toml_text(_config_text(str(repo_path)))
            materialized = _materialized(repo_path)
            model = FakeModel(
                json.dumps(
                    {
                        "summary": "Update the dependency file narrowly.",
                        "operations": [
                            {
                                "path": "requirements-dev.txt",
                                "action": "write_file",
                                "summary": "Add pytest-cov.",
                                "reason": "Coverage workflow requires it.",
                                "content": "pytest\npytest-cov\n",
                            }
                        ],
                        "validation": ["pytest -q"],
                        "risks": ["Dependency updates can affect CI resolution."],
                    }
                )
            )
            generator = DraftGenerator(config, model_client=model)

            result = generator.generate(materialized)

            self.assertEqual(result.status, "ready")
            self.assertEqual(model.calls, 1)
            self.assertEqual(result.operations[0].action, "write_file")
            self.assertEqual(result.operations[0].expected_sha256, materialized.edits[0].sha256)
            self.assertTrue(result.operations[0].content_sha256)
            self.assertIn("pytest-cov", result.operations[0].content_preview)

    def test_draft_generator_blocks_without_calling_model_when_materialized_intent_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            config = MrCleanConfig.from_toml_text(_config_text(str(repo_path)))
            materialized = _materialized(repo_path, status="blocked", edit_status="blocked")
            model = FakeModel("{}")
            generator = DraftGenerator(config, model_client=model)

            result = generator.generate(materialized)

            self.assertEqual(result.status, "blocked")
            self.assertEqual(model.calls, 0)
            self.assertEqual(result.operations[0].status, "blocked")
            self.assertIn("materialized intent is not ready", result.risks[-1])


if __name__ == "__main__":
    unittest.main()
