from __future__ import annotations

import unittest

from mrclean.config import MrCleanConfig, sample_config
from mrclean.dispatch import DispatchAction, DispatchCandidate
from mrclean.intents import IntentGenerator, IntentValidationError
from mrclean.models import CompletionResponse
from mrclean.runner import ActionExecution, RunSession


class FakeIntentModel:
    def __init__(self, content: str) -> None:
        self.content = content

    def complete(self, request):
        return CompletionResponse(content=self.content, raw={"provider": "fake", "model": request.model})


def _candidate() -> DispatchCandidate:
    return DispatchCandidate(
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
            DispatchAction("edit_patch", "edit", True, "allowed", "git diff --stat"),
        ),
    )


def _session() -> RunSession:
    return RunSession(
        repository="example/repo",
        number=32,
        branch="fix-ci",
        candidate_status="ready",
        run_status="prepared",
        executions=(
            ActionExecution(
                kind="inspect_signal",
                summary="inspect",
                command="gh pr view 32",
                status="executed",
                reason="command completed successfully",
                returncode=0,
                stdout="review context",
                stderr="",
            ),
        ),
    )


class IntentGeneratorTests(unittest.TestCase):
    def test_intent_generator_returns_validated_intent(self) -> None:
        config = MrCleanConfig.from_toml_text(sample_config())
        model = FakeIntentModel(
            """{
  "summary": "Fix the active CI issue narrowly.",
  "edits": [
    {
      "path": "requirements-dev.txt",
      "operation": "modify",
      "summary": "Add the missing test dependency.",
      "reason": "The failing coverage workflow needs pytest-cov."
    }
  ],
  "validation": ["pytest -q"],
  "risks": ["Dependency changes can affect CI resolution."]
}"""
        )

        intent = IntentGenerator(config, model_client=model).generate(_candidate(), _session())
        self.assertEqual(intent.summary, "Fix the active CI issue narrowly.")
        self.assertEqual(intent.edits[0].path, "requirements-dev.txt")
        self.assertEqual(intent.model_provider, "fake")

    def test_intent_generator_rejects_invalid_paths(self) -> None:
        config = MrCleanConfig.from_toml_text(sample_config())
        model = FakeIntentModel(
            """{
  "summary": "Bad path",
  "edits": [
    {
      "path": "../escape.txt",
      "operation": "modify",
      "summary": "escape",
      "reason": "bad"
    }
  ],
  "validation": [],
  "risks": []
}"""
        )

        with self.assertRaises(IntentValidationError):
            IntentGenerator(config, model_client=model).generate(_candidate(), _session())


if __name__ == "__main__":
    unittest.main()
